// Painel do Auditor: fiscalização, rastreabilidade e análise financeira (só leitura).
import { api } from "../api.js";
import { barChart } from "../chart.js";
import { dateTime, money, regionName } from "../format.js";
import { icon } from "../icons.js";
import { $, esc } from "../ui.js";
import { dailySeries, downloadCsv, exportButtons, kpi } from "../staff.js";
import { pageHead } from "./common.js";

const RULE_LABEL = { VALOR_ELEVADO: "Valor elevado", VELOCIDADE: "Frequência anormal", FALHAS_REPETIDAS: "Falhas repetidas",
  LIQUIDACAO_REJEITADA: "Liquidação rejeitada", SEM_APROVACAO: "Sem aprovação", PENDENTE_HA_MUITO: "Pendente há muito",
  FALHA_DE_PROCESSAMENTO: "Recuperação automática" };

export async function render({ root, navigate }) {
  const today = new Date().toISOString().slice(0, 10);
  const [o, sus, cons, audit] = await Promise.all([
    api("/admin/overview"), api("/admin/suspicious"), api("/admin/consistency"),
    api(`/admin/audit?date=${today}`).catch(() => null),
  ]);
  const count = (pred) => o.transactions.filter(pred).reduce((s, r) => s + Number(r.n), 0);
  const high = sus.findings.filter((f) => f.severity === "alta").length;

  root.innerHTML = `
    ${pageHead("Painel de auditoria", "Fiscalização independente de todas as regiões. Acesso exclusivamente de leitura.", exportButtons())}
    <div class="grid g-4 keep-2">
      ${kpi("Consistência entre regiões", cons.ok ? `<span style="color:var(--good-ink)">Íntegra</span>` : `<span style="color:var(--bad-ink)">${cons.problems.length} problema(s)</span>`,
        `${cons.checked_transactions} transferências verificadas`, "shield")}
      ${kpi("Registo de auditoria (hoje)", audit ? (audit.ok ? `<span style="color:var(--good-ink)">Íntegro</span>` : `<span style="color:var(--bad-ink)">Adulterado</span>`) : "—",
        audit ? `${Object.values(audit.files).reduce((s, f) => s + f.lines, 0)} registos em ${Object.keys(audit.files).length} nós` : "sem registos", "fingerprint")}
      ${kpi("Alertas", String(sus.findings.length), `${high} de severidade alta`, "alert")}
      ${kpi("Falhas de processamento", String(sus.failures.length), "transferências anuladas (30 dias)", "x")}
    </div>
    <div class="grid g-main" style="margin-top:20px">
      <section class="card"><div class="card-head"><div><h3>Transferências processadas por dia</h3><p class="hint">últimos 14 dias · ${count((r) => r.state === "CONFIRMADA")} processadas no total</p></div></div><div id="daily"></div></section>
      <section class="card card-pad"><h3>Volumes por região</h3>
        <dl class="kv" style="margin-top:8px">${Object.entries(o.balances).flatMap(([reg, rows]) => rows.map((b) => `
          <dt>${regionName(reg)} · ${esc(b.currency)}</dt><dd class="num">${esc(money(b.total, b.currency))}</dd>`)).join("")}
          <dt>Liquidações rejeitadas</dt><dd class="num">${o.settlement.find((s) => s.settlement_status === "REJEITADA")?.n || 0}</dd>
          <dt>Pedidos a aguardar aprovação</dt><dd class="num">${o.pending_approvals.n}</dd></dl>
        <div class="row wrap" style="margin-top:14px;gap:8px"><a class="btn btn-secondary btn-sm" href="#/admin/transfers">${icon("transfer")} Transferências</a>
          <a class="btn btn-secondary btn-sm" href="#/audit/events">${icon("doc")} Registos</a><a class="btn btn-secondary btn-sm" href="#/audit/compliance">${icon("shield")} Conformidade</a></div>
      </section>
    </div>
    <section class="card" style="margin-top:20px">
      <div class="card-head"><div><h3>Transações suspeitas e inconsistências</h3><p class="hint">Regras aplicadas aos registos reais dos últimos 30 dias</p></div></div>
      <div style="margin-top:10px">${sus.findings.length ? sus.findings.slice(0, 40).map((f) => `
        <div class="finding" ${f.tx_id ? `data-tx="${esc(f.tx_id)}" style="cursor:pointer"` : ""}>
          <span class="sev sev-${esc(f.severity)}" title="severidade ${esc(f.severity)}"></span>
          <div><b>${esc(RULE_LABEL[f.rule] || f.rule)}</b><div class="hint">${esc(f.detail)}</div><div class="hint">${esc(sus.rules[f.rule] || "")}</div></div>
          <span class="hint num" style="white-space:nowrap">${esc(dateTime(f.at))}</span></div>`).join("")
        : `<div class="empty"><div class="tx-icon in">${icon("check")}</div><h3>Nenhum alerta</h3><p>Nenhuma regra foi ativada no período.</p></div>`}</div>
    </section>
    <section class="card" style="margin-top:20px">
      <div class="card-head"><h3>Falhas de processamento</h3></div>
      <div class="table-wrap" style="margin-top:8px"><table class="table"><thead><tr><th>Data</th><th>Origem → Destino</th><th class="r">Montante</th><th>Motivo</th></tr></thead><tbody>
        ${sus.failures.slice(0, 30).map((t) => `<tr class="clickable" data-tx="${esc(t.tx_id)}"><td class="num" style="white-space:nowrap">${esc(dateTime(t.created_at))}</td>
          <td class="mono">${esc(t.from_iban)} → ${esc(t.to_iban)}</td><td class="r num">${esc(money(t.amount, t.from_currency))}</td><td class="soft">${esc(t.failure_reason || "—")}</td></tr>`).join("")
          || `<tr><td colspan="4"><div class="empty">Sem falhas no período.</div></td></tr>`}</tbody></table></div>
    </section>`;
  barChart($("#daily", root), dailySeries(o.daily), { format: (v) => `${v} transferências` });
  root.querySelectorAll("[data-tx]").forEach((el) => el.addEventListener("click", () => navigate(`/tx/${encodeURIComponent(el.dataset.tx)}`)));
  root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv(`relatorio-auditoria-${today}.csv`,
    ["tipo", "regra", "severidade", "data", "detalhe", "referencia"],
    [...sus.findings.map((f) => ["alerta", RULE_LABEL[f.rule] || f.rule, f.severity, f.at, f.detail, f.tx_id || f.iban || ""]),
     ...sus.failures.map((t) => ["falha", "Transferência anulada", "", t.created_at, `${t.amount} ${t.from_currency}: ${t.failure_reason || ""}`, t.tx_id]),
     ["consistencia", cons.ok ? "íntegra" : "problemas", "", new Date().toISOString(), `${cons.checked_transactions} verificadas, ${cons.problems.length} problemas`, ""]]));
}
