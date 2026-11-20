import { api } from "../api.js";
import { dateTime, money, regionName, REGION_CODES } from "../format.js";
import { icon } from "../icons.js";
import { $, busy, esc } from "../ui.js";
import { pageHead } from "./common.js";

const today = () => new Date().toISOString().slice(0, 10);

export async function render({ root, navigate }) {
  root.innerHTML = `
    ${pageHead("Auditoria e conformidade", "Verificações independentes sobre todos os centros de dados e sobre o registo de auditoria partilhado.",
      `<input class="input" type="date" id="day" value="${today()}" style="width:auto;min-height:40px" aria-label="Dia">`)}
    <div class="grid g-2">
      <section class="card card-pad" id="consistency"></section>
      <section class="card card-pad" id="chain"></section>
    </div>
    <section class="card" style="margin-top:20px" id="report"></section>
    <form class="card card-pad" id="find" style="margin-top:20px">
      <h3>Consultar transação</h3>
      <div class="row" style="margin-top:12px"><input class="input mono" id="tx" placeholder="Referência (tx_id)" spellcheck="false">
        <button class="btn btn-secondary" type="submit">${icon("search")} Abrir</button></div>
    </form>`;

  async function consistency() {
    const host = $("#consistency", root);
    host.innerHTML = `<h3>Consistência entre regiões</h3><div class="page-loading" style="min-height:140px"><span class="spinner"></span></div>`;
    const c = await api("/admin/consistency");
    host.innerHTML = `
      <div class="row between"><h3>Consistência entre regiões</h3><button class="btn btn-ghost btn-sm" id="re-c">${icon("refresh")} Verificar</button></div>
      <div class="row" style="gap:14px;margin:18px 0">
        <span class="receipt-icon ${c.ok ? "done" : "failed"}" style="margin:0;width:52px;height:52px">${icon(c.ok ? "check" : "alert")}</span>
        <div><b style="font-size:1.05rem">${c.ok ? "Sem discrepâncias" : `${c.problems.length} discrepância(s)`}</b>
          <p class="hint">Cada transferência processada tem exatamente um débito e um crédito; nenhuma anulada movimentou dinheiro.</p></div></div>
      <dl class="kv">
        <dt>Transferências verificadas</dt><dd class="num">${c.checked_transactions}</dd>
        <dt>Processadas</dt><dd class="num">${c.confirmed}</dd>
        <dt>Anuladas</dt><dd class="num">${c.aborted}</dd>
        <dt>Em curso</dt><dd class="num">${c.in_progress.length}</dd>
        <dt>Reservas pendentes (${REGION_CODES.join(" / ")})</dt><dd class="num">${REGION_CODES.map((r) => (c.prepared_xacts[r] || []).length).join(" / ")}</dd>
      </dl>
      ${c.problems.length ? `<div class="banner banner-bad" style="margin-top:14px">${icon("alert")}<span>${esc(JSON.stringify(c.problems.slice(0, 3)))}</span></div>` : ""}`;
    $("#re-c", root).addEventListener("click", consistency);
  }

  async function chain() {
    const host = $("#chain", root);
    const day = $("#day", root).value;
    host.innerHTML = `<h3>Registo de auditoria</h3><div class="page-loading" style="min-height:140px"><span class="spinner"></span></div>`;
    try {
      const a = await api(`/admin/audit?date=${day}`);
      host.innerHTML = `
        <div class="row between"><h3>Registo de auditoria</h3><span class="chip ${a.ok ? "status-done" : "status-failed"}">${icon(a.ok ? "shield" : "alert")}${a.ok ? "Íntegro" : "Adulteração detetada"}</span></div>
        <p class="hint" style="margin:8px 0 6px">Cada linha está encadeada por SHA-256 à anterior: qualquer alteração quebra a cadeia.</p>
        <ul class="list" style="margin:0 -24px -6px">${Object.entries(a.files).map(([f, v]) => `
          <li class="list-item"><span class="tx-icon ${v.ok ? "in" : "failed"}">${icon(v.ok ? "check" : "x")}</span>
            <span class="grow"><span class="title mono">${esc(f)}</span>
              <span class="sub">${v.lines} registos${v.ok ? "" : ` · primeira linha inválida: ${v.first_bad_line} — ${esc(v.reason)}`}</span></span></li>`).join("")}</ul>`;
    } catch (ex) {
      host.innerHTML = `<h3>Registo de auditoria</h3><div class="empty">${esc(ex.status === 404 ? "Sem registos para este dia." : ex.message)}</div>`;
    }
  }

  async function report() {
    const host = $("#report", root);
    const day = $("#day", root).value;
    try {
      const r = await api(`/admin/reports?date=${day}`);
      const st = r.transfers.by_state;
      const cash = r.cash || {};
      host.innerHTML = `
        <div class="card-head"><h3>Relatório diário · ${esc(day)}</h3><span class="hint">atualizado ${esc(dateTime(r.last_update))}</span></div>
        <div class="grid g-4 keep-2" style="padding:18px 24px 6px">
          <div class="stat"><div class="label">Processadas</div><div class="value num">${st.CONFIRMADA || 0}</div></div>
          <div class="stat"><div class="label">Anuladas</div><div class="value num">${st.ABORTADA || 0}</div></div>
          <div class="stat"><div class="label">Nacionais</div><div class="value num">${r.transfers.by_kind.LOCAL || 0}</div></div>
          <div class="stat"><div class="label">Internacionais</div><div class="value num">${r.transfers.by_kind.DISTRIBUIDA || 0}</div></div>
        </div>
        <div class="table-wrap" style="padding:0 8px 8px"><table class="table"><thead><tr><th>Região</th><th class="r">Volume transferido</th><th class="r">Depósitos</th><th class="r">Levantamentos</th></tr></thead><tbody>
          ${REGION_CODES.map((reg) => `<tr><td>${regionName(reg)}</td>
            <td class="r num">${Object.entries(r.transfers.volume_by_region[reg] || {}).map(([c, v]) => esc(money(v, c))).join("<br>") || "—"}</td>
            <td class="r num">${cash.DEPOSITO?.[reg]?.count || 0}</td><td class="r num">${cash.LEVANTAMENTO?.[reg]?.count || 0}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="hint" style="padding:0 24px 18px">Relatório partilhado no sistema de ficheiros distribuído, escrito em simultâneo por ${Object.keys(r.updates_by_node).length} nós (${esc(Object.keys(r.updates_by_node).join(", "))}).</p>`;
    } catch (ex) {
      host.innerHTML = `<div class="card-head"><h3>Relatório diário</h3></div><div class="empty">${esc(ex.status === 404 ? "Sem atividade neste dia." : ex.message)}</div>`;
    }
  }

  $("#day", root).addEventListener("change", () => { chain(); report(); });
  $("#find", root).addEventListener("submit", (e) => { e.preventDefault(); const v = $("#tx", root).value.trim(); if (v) navigate(`/tx/${encodeURIComponent(v)}`); });
  await Promise.all([consistency(), chain(), report()]);
  void busy;
}
