// Relatórios financeiros (Administrador e Auditor): período, volumes, estados, regiões,
// relatório diário partilhado (NFS) e exportação CSV/PDF.
import { api } from "../api.js";
import { barChart } from "../chart.js";
import { kindLabel, money, number, transferStatus, regionName } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, esc } from "../ui.js";
import { dailySeries, downloadCsv } from "../staff.js";
import { pageHead } from "./common.js";

const PERIODS = [[7, "7 dias"], [14, "14 dias"], [30, "30 dias"], [90, "90 dias"]];

export async function render({ root }) {
  let days = 30;
  async function draw() {
    const today = new Date().toISOString().slice(0, 10);
    const [o, daily] = await Promise.all([api(`/admin/overview?days=${days}`), api(`/admin/reports?date=${today}`).catch(() => null)]);
    const total = o.transactions.reduce((s, r) => s + Number(r.n), 0);
    const byState = {}, byKind = {};
    o.transactions.forEach((r) => { byState[r.state] = (byState[r.state] || 0) + Number(r.n); byKind[r.kind] = (byKind[r.kind] || 0) + Number(r.n); });
    const volume = {};
    o.daily.forEach((d) => { volume[d.currency] = (volume[d.currency] || 0) + Number(d.volume); });
    const confirmedPeriod = o.daily.reduce((s, d) => s + Number(d.confirmed), 0);
    const failedPeriod = o.daily.reduce((s, d) => s + Number(d.failed), 0);
    const successRate = confirmedPeriod + failedPeriod ? (confirmedPeriod / (confirmedPeriod + failedPeriod)) * 100 : 0;

    root.innerHTML = `
      ${pageHead("Relatórios", "Volumes financeiros e atividade da instituição, calculados sobre os registos do coordenador e dos shards.",
        `<div class="segmented" role="group" aria-label="Período">${PERIODS.map(([d, l]) => `<button data-d="${d}" aria-pressed="${d === days}">${l}</button>`).join("")}</div>
         <button class="btn btn-secondary" data-export="csv">${icon("download")} CSV</button><button class="btn btn-secondary" data-export="pdf">${icon("print")} PDF</button>`)}
      <section class="panel"><div class="metric-strip" style="--n:4">
        <div class="metric"><span class="m-label">${icon("check")} Processadas no período</span><span class="m-value">${confirmedPeriod}</span><span class="m-sub">${failedPeriod} falhadas</span></div>
        <div class="metric"><span class="m-label">${icon("shield")} Taxa de sucesso</span><span class="m-value">${number(successRate, 1)}%</span><span class="m-sub">processadas / (processadas + falhadas)</span></div>
        <div class="metric"><span class="m-label">${icon("transfer")} Volume processado</span><span class="m-value" style="font-size:1.25rem">${Object.entries(volume).map(([c, v]) => esc(money(v, c))).join(" · ") || "—"}</span><span class="m-sub">por moeda de origem</span></div>
        <div class="metric"><span class="m-label">${icon("clock")} Aprovações pendentes</span><span class="m-value">${o.pending_approvals.n}</span><span class="m-sub">pedidos de operadores</span></div>
      </div></section>
      <div class="bento mt">
        <section class="panel c-8"><div class="panel-head"><div><h3>Transferências processadas por dia</h3><div class="sub">últimos ${days} dias</div></div></div>
          <div class="panel-body flush" id="chart"></div></section>
        <section class="panel c-4"><div class="panel-head"><h3>Distribuição</h3></div><div class="panel-body">
          <div class="section-title" style="margin-top:0">Por estado</div>
          <dl class="kv">${Object.entries(byState).map(([s, n]) => `<dt>${esc(transferStatus(s).label)} <span class="hint">(${esc(s.toLowerCase())})</span></dt><dd class="num">${n} · ${number((n / Math.max(total, 1)) * 100, 0)}%</dd>`).join("")}</dl>
          <div class="section-title">Por tipo</div>
          <dl class="kv">${Object.entries(byKind).map(([k, n]) => `<dt>${esc(kindLabel(k))}</dt><dd class="num">${n}</dd>`).join("")}</dl>
          <div class="section-title">Liquidação com o banco correspondente</div>
          <dl class="kv">${o.settlement.map((s) => `<dt>${esc(s.settlement_status)}</dt><dd class="num">${s.n}</dd>`).join("")}</dl>
        </div></section>
      </div>
      <div class="bento mt">
        <section class="panel c-7"><div class="panel-head"><h3>Volume diário por moeda</h3></div>
          <div class="table-scroll" style="--table-h:420px"><table class="table"><thead><tr><th>Dia</th><th>Moeda</th><th class="r">Processadas</th><th class="r">Falhadas</th><th class="w-money">Volume</th></tr></thead><tbody>
            ${[...o.daily].reverse().map((d) => `<tr><td class="num">${esc(d.day.slice(0, 10))}</td><td><span class="cur-badge">${esc(d.currency)}</span></td><td class="r num">${d.confirmed}</td><td class="r num">${d.failed}</td><td class="w-money num">${esc(money(d.volume, d.currency))}</td></tr>`).join("") || `<tr><td colspan="5"><div class="empty-sm">Sem atividade no período.</div></td></tr>`}
          </tbody></table></div></section>
        <section class="panel c-5"><div class="panel-head"><h3>Saldos sob custódia</h3></div><div class="panel-body flush">
          <table class="table"><thead><tr><th>Região</th><th>Moeda</th><th class="r">Contas</th><th class="w-money">Total</th></tr></thead><tbody>
            ${Object.entries(o.balances).flatMap(([reg, rows]) => rows.map((b) => `<tr><td>${regionName(reg)}</td><td><span class="cur-badge">${esc(b.currency)}</span></td><td class="r num">${b.accounts}</td><td class="w-money num">${esc(money(b.total, b.currency))}</td></tr>`)).join("")}
          </tbody></table></div>
          ${daily ? `<div class="panel-foot"><span>Relatório de hoje (NFS): ${Object.keys(daily.updates_by_node || {}).length} nós a escrever · atualizado ${esc((daily.last_update || "").replace("T", " ").slice(0, 16))}</span></div>` : ""}
        </section>
      </div>`;
    barChart($("#chart", root), dailySeries(o.daily, days), { format: (v) => `${v} transferências` });
    $$("[data-d]", root).forEach((b) => b.addEventListener("click", () => { days = Number(b.dataset.d); draw(); }));
    root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
    root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv(`relatorio-${days}d-${today}.csv`,
      ["dia", "moeda", "processadas", "falhadas", "volume"], o.daily.map((d) => [d.day.slice(0, 10), d.currency, d.confirmed, d.failed, d.volume])));
  }
  await draw();
}
