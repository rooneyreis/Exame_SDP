// Todas as transferências (Administrador, Operador, Auditor): filtros, pesquisa, quem iniciou/aprovou,
// paginação e exportação CSV/PDF.
import { api } from "../api.js";
import { kindLabel, transferStatus } from "../format.js";
import { icon } from "../icons.js";
import { $, esc } from "../ui.js";
import { bindRowLinks, downloadCsv, exportButtons, ROLE_LABEL, transfersTable, users, who } from "../staff.js";
import { pageHead } from "./common.js";

const PAGE = 50;

export async function render({ root, claims, navigate }) {
  const dir = await users();
  const f = { state: "", kind: "", initiated_role: "", q: "", date_from: "", date_to: "", offset: 0 };
  root.innerHTML = `
    ${pageHead("Transferências", claims.role === "auditor" ? "Histórico completo, com o responsável por cada ordem e por cada aprovação." : "Todas as transferências da instituição.", exportButtons())}
    <div class="card">
      <div class="toolbar">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="IBAN ou referência" aria-label="Pesquisar"></div>
        <select class="select" id="state" style="width:auto" aria-label="Estado"><option value="">Todos os estados</option>
          <option value="CONFIRMADA">Processadas</option><option value="ABORTADA">Falhadas</option><option value="DECISAO_COMMIT">Pendentes (decididas)</option><option value="PREPARANDO">Pendentes (a preparar)</option></select>
        <select class="select" id="kind" style="width:auto" aria-label="Tipo"><option value="">Nacionais e internacionais</option><option value="LOCAL">Nacionais</option><option value="DISTRIBUIDA">Internacionais</option></select>
        <select class="select" id="role" style="width:auto" aria-label="Iniciada por"><option value="">Iniciadas por todos</option><option value="cliente">Clientes</option><option value="operador">Operadores</option></select>
        <input class="input" type="date" id="from" style="width:auto" aria-label="De">
        <input class="input" type="date" id="to" style="width:auto" aria-label="Até">
      </div>
      <div id="table"></div>
      <div class="pager"><span class="hint" id="count"></span><div class="row"><button class="btn btn-secondary btn-sm" id="prev">${icon("chevronLeft")}</button><button class="btn btn-secondary btn-sm" id="next">${icon("chevronRight")}</button></div></div>
    </div>`;

  let data = { total: 0, items: [] };
  async function load() {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(f.offset) });
    for (const k of ["state", "kind", "initiated_role", "q", "date_from", "date_to"]) if (f[k]) p.set(k, f[k]);
    data = await api(`/admin/transfers?${p}`);
    $("#table", root).innerHTML = transfersTable(data.items, dir);
    $("#count", root).textContent = data.total ? `${f.offset + 1}–${f.offset + data.items.length} de ${data.total}` : "0 resultados";
    $("#prev", root).disabled = f.offset === 0;
    $("#next", root).disabled = f.offset + PAGE >= data.total;
    bindRowLinks(root, navigate);
  }
  let timer;
  $("#q", root).addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { f.q = e.target.value.trim(); f.offset = 0; load(); }, 300); });
  [["state", "state"], ["kind", "kind"], ["role", "initiated_role"], ["from", "date_from"], ["to", "date_to"]].forEach(([id, key]) =>
    $(`#${id}`, root).addEventListener("change", (e) => { f[key] = e.target.value; f.offset = 0; load(); }));
  $("#prev", root).addEventListener("click", () => { f.offset = Math.max(0, f.offset - PAGE); load(); });
  $("#next", root).addEventListener("click", () => { f.offset += PAGE; load(); });
  root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  root.querySelector('[data-export="csv"]').addEventListener("click", async () => {
    const p = new URLSearchParams({ limit: "1000", offset: "0" });
    for (const k of ["state", "kind", "initiated_role", "q", "date_from", "date_to"]) if (f[k]) p.set(k, f[k]);
    const all = await api(`/admin/transfers?${p}`);
    downloadCsv(`transferencias-${new Date().toISOString().slice(0, 10)}.csv`,
      ["data", "tx_id", "origem", "destino", "tipo", "montante", "moeda", "creditado", "moeda_destino", "taxa", "estado", "motivo_falha",
        "liquidacao", "iniciada_por", "perfil", "aprovada_por", "sha256_pedido"],
      all.items.map((t) => [t.created_at, t.tx_id, t.from_iban, t.to_iban, kindLabel(t.kind), t.amount, t.from_currency, t.converted_amount,
        t.to_currency, t.fx_rate, transferStatus(t.state).label, t.failure_reason, t.settlement_status, who(dir, t.initiated_by),
        ROLE_LABEL[t.initiated_role] || t.initiated_role, who(dir, t.approved_by), t.request_sha256]));
  });
  await load();
  void esc;
}
