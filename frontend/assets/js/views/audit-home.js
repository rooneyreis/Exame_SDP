// Painel do Auditor: verificações independentes, só leitura.
//  [ /admin/consistency: veredicto + números (6) ] [ cadeia de auditoria: veredicto por nó (6) ]
//  [ eventos recentes do registo (7)             ] [ transações abortadas (5)                  ]
//  [ alertas de fiscalização (12)                                                           ]
import { api } from "../api.js";
import { dateTime, money, REGION_CODES, regionName, time } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, esc } from "../ui.js";
import { downloadCsv, exportButtons } from "../staff.js";
import { pageHead } from "./common.js";

const RULE_LABEL = { VALOR_ELEVADO: "Valor elevado", VELOCIDADE: "Frequência anormal", FALHAS_REPETIDAS: "Falhas repetidas",
  LIQUIDACAO_REJEITADA: "Liquidação rejeitada", SEM_APROVACAO: "Sem aprovação", PENDENTE_HA_MUITO: "Pendente há muito",
  FALHA_DE_PROCESSAMENTO: "Recuperação automática" };

function consistencyHtml(c) {
  const ok = c.ok;
  return `
    <div class="verdict ${ok ? "ok" : "bad"}"><span class="v-icon">${icon(ok ? "shield" : "alert")}</span>
      <div><b>${ok ? "Sem discrepâncias entre regiões" : `${c.problems.length} discrepância(s) encontrada(s)`}</b>
        <p>Cada transferência processada tem exatamente um débito e um crédito; nenhuma anulada movimentou dinheiro.</p></div></div>
    <div class="mini-stats" style="--n:4">
      <div><span>Verificadas</span><b>${c.checked_transactions}</b></div><div><span>Processadas</span><b>${c.confirmed}</b></div>
      <div><span>Anuladas</span><b>${c.aborted}</b></div><div><span>Em curso</span><b>${c.in_progress.length}</b></div></div>
    <div class="mini-stats" style="--n:${REGION_CODES.length}">
      ${REGION_CODES.map((r) => `<div><span>Reservas pendentes · ${r}</span><b>${(c.prepared_xacts?.[r] || []).length}</b></div>`).join("")}</div>
    ${c.problems.length ? `<div class="banner banner-bad" style="margin:14px 22px">${icon("alert")}<span class="mono" style="font-size:.78rem">${esc(JSON.stringify(c.problems.slice(0, 3)))}</span></div>` : ""}`;
}

function chainHtml(audit) {
  if (!audit) return `<div class="empty-sm">Sem registos de auditoria hoje.</div>`;
  const files = Object.entries(audit.files);
  const lines = files.reduce((s, [, f]) => s + f.lines, 0);
  return `
    <div class="verdict ${audit.ok ? "ok" : "bad"}"><span class="v-icon">${icon(audit.ok ? "fingerprint" : "alert")}</span>
      <div><b>${audit.ok ? "Cadeia de hashes íntegra" : "Adulteração detetada"}</b>
        <p>${lines} registos de ${files.length} nós, encadeados por SHA-256 no NFS.</p></div></div>
    <div style="border-top:1px solid var(--line)">${files.map(([name, f]) => `
      <div class="chain-row"><span class="status-dot ${f.ok ? "" : "down"}"></span><span class="mono">${esc(name.replace(/\.log$/, ""))}</span>
        <span class="hint num">${f.lines} linhas</span>
        <span class="chip ${f.ok ? "status-done" : "status-failed"}">${f.ok ? "íntegra" : `linha ${f.first_bad_line}`}</span></div>`).join("")}</div>`;
}

export async function render({ root, navigate }) {
  const today = new Date().toISOString().slice(0, 10);
  const [cons, audit, events, sus] = await Promise.all([
    api("/admin/consistency"), api(`/admin/audit?date=${today}`).catch(() => null),
    api(`/admin/audit/events?date=${today}&limit=10`).catch(() => ({ items: [] })), api("/admin/suspicious"),
  ]);

  root.innerHTML = `
    ${pageHead("Painel de auditoria", "Verificações independentes sobre todas as regiões. Acesso exclusivamente de leitura.", exportButtons())}
    <div class="bento">
      <section class="panel c-6"><div class="panel-head"><div><h3>Consistência do 2PC</h3><div class="sub">/admin/consistency · todos os shards</div></div>
        <button class="btn btn-secondary btn-sm" id="re-cons">${icon("refresh")} Verificar</button></div>
        <div id="cons">${consistencyHtml(cons)}</div></section>
      <section class="panel c-6"><div class="panel-head"><div><h3>Cadeia de auditoria</h3><div class="sub">registo de hoje, validado linha a linha</div></div>
        <button class="btn btn-secondary btn-sm" id="re-chain">${icon("refresh")} Verificar</button></div>
        <div id="chain">${chainHtml(audit)}</div></section>
    </div>
    <div class="bento">
      <section class="panel c-7"><div class="panel-head"><div><h3>Eventos recentes</h3><div class="sub">${events.total ?? events.items.length} eventos hoje em todos os nós</div></div><a class="link-btn" href="#/audit/events">Ver registo</a></div>
        <div>${events.items.map((e) => `
          <div class="event-row"><span class="mono">${esc(time(e.ts))}</span>
            <span style="min-width:0"><b>${esc(e.event || "")}</b><span class="sub">${esc(e._file?.replace(/\.log$/, "") || "")}${e.actor_role ? ` · ${esc(e.actor_role)}` : ""}${e.iban ? ` · ${esc(e.iban)}` : ""}${e.tx_id ? ` · ${esc(String(e.tx_id).slice(0, 8))}` : ""}</span></span>
            <span class="chip ${e.result && e.result !== "OK" ? "status-failed" : ""}">${esc(e.result || "OK")}</span></div>`).join("") ||
          `<div class="empty-sm">Sem eventos hoje.</div>`}</div></section>
      <section class="panel c-5"><div class="panel-head"><div><h3>Transações abortadas</h3><div class="sub">últimos 30 dias · ${sus.failures.length} no total</div></div></div>
        <div>${sus.failures.slice(0, 7).map((t) => `
          <div class="queue-item" data-tx="${esc(t.tx_id)}" style="cursor:pointer">
            <span class="tx-icon failed">${icon("x")}</span>
            <span class="q-main"><b>${esc(money(t.amount, t.from_currency))}</b><span>${esc(t.failure_reason || "—")}</span></span>
            <span class="hint num" style="white-space:nowrap">${esc(dateTime(t.created_at))}</span></div>`).join("") ||
          `<div class="empty-sm">Nenhuma transação abortada.</div>`}</div></section>
    </div>
    <section class="panel mt"><div class="panel-head"><div><h3>Alertas de fiscalização</h3><div class="sub">regras aplicadas aos registos reais dos últimos 30 dias</div></div><a class="link-btn" href="#/audit/compliance">Conformidade</a></div>
      <div>${sus.findings.slice(0, 8).map((f) => `
        <div class="finding" ${f.tx_id ? `data-tx="${esc(f.tx_id)}" style="cursor:pointer"` : ""}>
          <span class="sev sev-${esc(f.severity)}" title="severidade ${esc(f.severity)}"></span>
          <div><b>${esc(RULE_LABEL[f.rule] || f.rule)}</b><div class="hint">${esc(f.detail)}</div></div>
          <span class="hint num" style="white-space:nowrap">${esc(dateTime(f.at))}</span></div>`).join("") ||
        `<div class="empty-sm">${icon("check")} Nenhuma regra foi ativada no período.</div>`}</div></section>`;

  $("#re-cons", root).addEventListener("click", async (e) => {
    busy(e.currentTarget, true, "A verificar…");
    try { $("#cons", root).innerHTML = consistencyHtml(await api("/admin/consistency")); } finally { busy(e.currentTarget, false); }
  });
  $("#re-chain", root).addEventListener("click", async (e) => {
    busy(e.currentTarget, true, "A verificar…");
    try { $("#chain", root).innerHTML = chainHtml(await api(`/admin/audit?date=${today}`).catch(() => null)); } finally { busy(e.currentTarget, false); }
  });
  $$("[data-tx]", root).forEach((el) => el.addEventListener("click", () => navigate(`/tx/${encodeURIComponent(el.dataset.tx)}`)));
  root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv(`relatorio-auditoria-${today}.csv`,
    ["tipo", "regra", "severidade", "data", "detalhe", "referencia"],
    [...sus.findings.map((f) => ["alerta", RULE_LABEL[f.rule] || f.rule, f.severity, f.at, f.detail, f.tx_id || f.iban || ""]),
     ...sus.failures.map((t) => ["falha", "Transferência anulada", "", t.created_at, `${t.amount} ${t.from_currency}: ${t.failure_reason || ""}`, t.tx_id]),
     ["consistencia", cons.ok ? "íntegra" : "problemas", "", new Date().toISOString(), `${cons.checked_transactions} verificadas, ${cons.problems.length} problemas`, ""]]));
}
