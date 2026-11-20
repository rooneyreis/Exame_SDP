// Notificações derivadas dos registos reais (sem endpoint próprio, sem dados inventados).
// O estado "lida" fica neste dispositivo, por utilizador.
import { api, session } from "./api.js";
import { activity, myAccounts } from "./data.js";
import { iban, money } from "./format.js";

const DAY = 86400000;
let cache = { at: 0, sub: null, items: [] };

function readKey() { return `gs.${session.claims?.sub}.notif.read`; }
function readSet() { try { return new Set(JSON.parse(localStorage.getItem(readKey())) || []); } catch { return new Set(); } }
function saveRead(set) { try { localStorage.setItem(readKey(), JSON.stringify([...set].slice(-500))); } catch { /* ignore */ } }

export function isRead(id) { return readSet().has(id); }
export function markRead(ids) { const s = readSet(); ids.forEach((i) => s.add(i)); saveRead(s); }
export function unread(items) { const s = readSet(); return items.filter((n) => !s.has(n.id)); }

async function forClient() {
  const accounts = await myAccounts();
  const items = await activity(accounts, { limit: 60 });
  const since = Date.now() - 14 * DAY;
  return items.filter((i) => new Date(i.date).getTime() >= since).flatMap((i) => {
    const href = `/tx/${encodeURIComponent(i.txId)}`;
    if (i.status.key === "failed") return [{ id: `f:${i.txId}`, kind: "bad", icon: "x", title: "Transferência não realizada", text: `${money(i.amount, i.currency)} para ${i.counterparty ? iban(i.counterparty) : "—"}. Nenhum valor foi debitado.`, at: i.date, href }];
    if (i.status.key === "pending") return [{ id: `p:${i.txId}`, kind: "warn", icon: "clock", title: "Transferência em processamento", text: `${money(i.amount, i.currency)} · concluída automaticamente`, at: i.date, href }];
    if (i.direction === "in" && i.origin === "TRANSFERENCIA") return [{ id: `in:${i.txId}`, kind: "good", icon: "arrowDown", title: "Recebeu uma transferência", text: `${money(i.amount, i.currency)} na conta ${i.account.slice(-4)}`, at: i.date, href }];
    if (i.origin === "DEPOSITO") return [{ id: `dep:${i.txId}`, kind: "info", icon: "deposit", title: "Depósito creditado", text: `${money(i.amount, i.currency)} na conta ${i.account.slice(-4)}`, at: i.date, href }];
    return [];
  });
}

async function forOperator() {
  const [reqs, kyc] = await Promise.all([api("/transfer-requests?mine=true&limit=100"), api("/admin/users?status=PENDENTE_VERIFICACAO").catch(() => [])]);
  const since = Date.now() - 14 * DAY;
  const out = reqs.filter((r) => new Date(r.updated_at || r.created_at).getTime() >= since).flatMap((r) => {
    const base = { at: r.decided_at || r.updated_at || r.created_at, href: r.tx_id ? `/tx/${r.tx_id}` : "/ops/requests" };
    if (r.effective_status === "REJEITADA") return [{ ...base, id: `rej:${r.id}`, kind: "bad", icon: "x", title: "Pedido rejeitado", text: `${money(r.amount, r.currency)} · ${r.decision_reason || "sem motivo"}` }];
    if (r.effective_status === "FALHADA") return [{ ...base, id: `fail:${r.id}`, kind: "bad", icon: "alert", title: "Transferência falhada", text: `${money(r.amount, r.currency)} · ${r.failure_reason || ""}` }];
    if (r.effective_status === "EXECUTADA" && r.requires_approval) return [{ ...base, id: `ok:${r.id}`, kind: "good", icon: "check", title: "Pedido aprovado e executado", text: `${money(r.amount, r.currency)} para ${r.beneficiary_name || iban(r.to_iban)}` }];
    return [];
  });
  const pending = reqs.filter((r) => r.effective_status === "PENDENTE_APROVACAO");
  if (pending.length) out.push({ id: `pend:${pending.map((r) => r.id).join(",")}`, kind: "warn", icon: "clock", title: `${pending.length} pedido(s) a aguardar aprovação`, text: "Decisão de um administrador", at: pending[0].created_at, href: "/ops/requests" });
  if (kyc.length) out.push({ id: `kyc:${kyc.length}:${kyc[kyc.length - 1].id}`, kind: "info", icon: "users", title: `${kyc.length} pedido(s) de abertura de conta`, text: "Verificação de identidade pendente", at: kyc[kyc.length - 1].created_at, href: "/ops/kyc" });
  return out;
}

async function forAdmin() {
  const [reqs, kyc, sus, status] = await Promise.all([
    api("/transfer-requests?status=PENDENTE_APROVACAO&limit=50"), api("/admin/users?status=PENDENTE_VERIFICACAO").catch(() => []),
    api("/admin/suspicious?days=7").catch(() => ({ findings: [] })), api("/admin/status").catch(() => null)]);
  const out = reqs.map((r) => ({ id: `appr:${r.id}`, kind: "warn", icon: "check", title: "Transferência aguarda aprovação", text: `${money(r.amount, r.currency)} · ${iban(r.from_iban)} → ${iban(r.to_iban)}`, at: r.created_at, href: "/admin/approvals" }));
  if (kyc.length) out.push({ id: `kyc:${kyc.length}:${kyc[kyc.length - 1].id}`, kind: "info", icon: "users", title: `${kyc.length} cliente(s) a aguardar KYC`, text: "Abertura de contas pendente", at: kyc[kyc.length - 1].created_at, href: "/ops/kyc" });
  sus.findings.filter((f) => f.severity === "alta").slice(0, 10).forEach((f) => out.push({ id: `sus:${f.rule}:${f.tx_id || f.iban}`, kind: "bad", icon: "alert", title: "Alerta de auditoria", text: f.detail, at: f.at, href: f.tx_id ? `/tx/${f.tx_id}` : "/audit/compliance" }));
  if (status && !status.all_up) {
    const down = [...Object.entries(status.services), ...Object.entries(status.databases)].filter(([, v]) => !v.up).map(([n]) => n);
    out.push({ id: `down:${down.join(",")}`, kind: "bad", icon: "server", title: "Nós indisponíveis", text: down.join(", "), at: new Date().toISOString(), href: "/admin/infra" });
  }
  return out;
}

async function forAuditor() {
  const today = new Date().toISOString().slice(0, 10);
  const [sus, cons, audit] = await Promise.all([api("/admin/suspicious?days=7").catch(() => ({ findings: [] })),
    api("/admin/consistency").catch(() => null), api(`/admin/audit?date=${today}`).catch(() => null)]);
  const out = sus.findings.slice(0, 20).map((f) => ({ id: `sus:${f.rule}:${f.tx_id || f.iban}:${f.at}`, kind: f.severity === "alta" ? "bad" : f.severity === "media" ? "warn" : "info",
    icon: "alert", title: { VALOR_ELEVADO: "Valor elevado", VELOCIDADE: "Frequência anormal", FALHAS_REPETIDAS: "Falhas repetidas", LIQUIDACAO_REJEITADA: "Liquidação rejeitada", SEM_APROVACAO: "Operação sem aprovação", PENDENTE_HA_MUITO: "Transação pendente há muito", FALHA_DE_PROCESSAMENTO: "Recuperação automática" }[f.rule] || f.rule,
    text: f.detail, at: f.at, href: f.tx_id ? `/tx/${f.tx_id}` : "/audit" }));
  if (cons && !cons.ok) out.push({ id: `cons:${cons.problems.length}`, kind: "bad", icon: "shield", title: "Inconsistência entre regiões", text: `${cons.problems.length} problema(s) detetado(s)`, at: new Date().toISOString(), href: "/audit/compliance" });
  if (audit && !audit.ok) out.push({ id: `chain:${today}`, kind: "bad", icon: "fingerprint", title: "Registo de auditoria adulterado", text: "A cadeia de hashes de hoje não é válida", at: new Date().toISOString(), href: "/audit/events" });
  return out;
}

export async function notifications({ fresh = false } = {}) {
  const sub = session.claims?.sub;
  if (!fresh && cache.sub === sub && Date.now() - cache.at < 60_000) return cache.items;
  const role = session.claims?.role;
  const fn = { cliente: forClient, operador: forOperator, admin: forAdmin, auditor: forAuditor }[role];
  const items = fn ? await fn().catch(() => []) : [];
  items.sort((a, b) => new Date(b.at) - new Date(a.at));
  cache = { at: Date.now(), sub, items };
  return items;
}
