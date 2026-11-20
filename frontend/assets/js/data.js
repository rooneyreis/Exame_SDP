// Camada de dados: junta as respostas das APIs existentes num modelo pensado para o ecrã.
// Não há lógica de negócio aqui — só leitura e apresentação.
import { api } from "./api.js";
import { iban as fmtIban, originLabel, transferStatus } from "./format.js";
import { beneficiaries, sentTransfers } from "./store.js";

const transferCache = new Map();   // tx_id -> detalhe (ou null se não for visível para este utilizador)

export async function myAccounts() {
  return api("/accounts");
}

export async function fxRates() {
  const rows = await api("/fx-rates");
  const map = {};
  for (const r of rows) (map[r.base] ||= {})[r.quote] = Number(r.rate);
  return map;
}

export function convert(amount, from, to, rates) {
  if (from === to) return Number(amount);
  const r = rates?.[from]?.[to];
  return r ? Number(amount) * r : null;
}

export async function movements(iban, limit = 100) {
  return api(`/accounts/${encodeURIComponent(iban)}/movements?limit=${limit}`);
}

export async function transfer(txId, { fresh = false } = {}) {
  if (!fresh && transferCache.has(txId)) return transferCache.get(txId);
  try {
    const t = await api(`/transfers/${encodeURIComponent(txId)}`);
    transferCache.set(txId, t);
    return t;
  } catch (e) {
    if (e.status === 404) { transferCache.set(txId, null); return null; }
    throw e;
  }
}

async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (i < items.length) { const k = i++; out[k] = await fn(items[k]); }
  }));
  return out;
}

function counterpartyName(ibanValue) {
  return beneficiaries.byIban(ibanValue)?.name || null;
}

/**
 * Atividade unificada do cliente:
 *  - movimentos de todas as contas (o que realmente aconteceu nos shards)
 *  - + transferências submetidas neste dispositivo que não geraram movimentos (falhadas/pendentes)
 * Cada item: { key, txId, date, direction, amount, currency, account, counterparty, title, category, status, kind, settlement }
 */
export async function activity(accounts, { limit = 100 } = {}) {
  await beneficiaries.load().catch(() => []);
  const perAccount = await Promise.all(accounts.map((a) => movements(a.iban, limit).then((ms) => ms.map((m) => ({ ...m, account: a })))));
  const all = perAccount.flat();

  const transferIds = [...new Set(all.filter((m) => m.origin === "TRANSFERENCIA").map((m) => m.tx_id))];
  const local = sentTransfers.all().filter((t) => !all.some((m) => m.tx_id === t.tx_id));
  const ids = [...new Set([...transferIds, ...local.map((t) => t.tx_id)])];
  const details = new Map((await mapLimit(ids, 6, async (id) => [id, await transfer(id).catch(() => null)])));

  const items = all.map((m) => {
    const t = m.origin === "TRANSFERENCIA" ? details.get(m.tx_id) : null;
    const direction = m.type === "CREDITO" ? "in" : "out";
    const counterparty = t ? (direction === "out" ? t.to_iban : t.from_iban) : null;
    const name = counterparty ? counterpartyName(counterparty) : null;
    return {
      key: `${m.tx_id}:${m.account.iban}:${m.type}`,
      txId: m.tx_id, date: m.created_at, direction,
      amount: Number(m.amount), currency: m.currency, balanceAfter: Number(m.balance_after),
      account: m.account.iban, counterparty,
      title: name || (m.origin === "TRANSFERENCIA" ? (direction === "out" ? (counterparty ? `Para ${fmtIban(counterparty)}` : "Transferência enviada") : "Transferência recebida") : originLabel(m.origin, m.type)),
      category: originLabel(m.origin, m.type), origin: m.origin,
      status: t ? transferStatus(t.state) : transferStatus("CONFIRMADA"),
      kind: t?.kind || (m.origin === "TRANSFERENCIA" ? null : "LOCAL"),
      settlement: t?.settlement_status, transfer: t,
    };
  });

  for (const s of local) {
    const t = details.get(s.tx_id);
    const state = t?.state || s.state || "INICIADA";
    items.push({
      key: `local:${s.tx_id}`, txId: s.tx_id, date: t?.created_at || s.at, direction: "out",
      amount: Number(t?.amount ?? s.amount), currency: t?.from_currency || s.currency,
      account: s.from_iban, counterparty: s.to_iban,
      title: counterpartyName(s.to_iban) || s.beneficiary || `Para ${fmtIban(s.to_iban)}`,
      category: "Transferência enviada", origin: "TRANSFERENCIA",
      status: transferStatus(state), kind: t?.kind, settlement: t?.settlement_status, transfer: t,
      failureReason: t?.failure_reason,
    });
  }
  return items.sort((a, b) => new Date(b.date) - new Date(a.date));
}

/** Série temporal do saldo de uma conta (pontos {t, v}) a partir dos movimentos. */
export function balanceSeries(moves, currentBalance) {
  // Os movimentos vêm por id (ordem real em que a conta foi bloqueada e alterada). O created_at é a
  // hora de INÍCIO da transação no PostgreSQL (now()), por isso, com transferências concorrentes,
  // pode andar para trás entre movimentos seguidos: força-se um eixo temporal monótono.
  let last = 0;
  const pts = [...moves].sort((a, b) => a.id - b.id).map((m) => {
    last = Math.max(last, new Date(m.created_at).getTime());
    return { t: last, v: Number(m.balance_after) };
  });
  if (currentBalance != null) pts.push({ t: Date.now(), v: Number(currentBalance) });
  return pts;
}
