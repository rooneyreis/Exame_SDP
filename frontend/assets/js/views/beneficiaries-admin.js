// Beneficiários dos clientes (Operador e Administrador gerem; Auditor consulta).
import { api } from "../api.js";
import { dateTime, iban } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, confirmSheet, esc, fieldError, sheet, toast } from "../ui.js";
import { users, who } from "../staff.js";
import { pageHead } from "./common.js";

export async function render({ root, claims }) {
  const canManage = claims.role === "operador" || claims.role === "admin";
  const dir = await users();
  const clients = [...dir.values()].filter((u) => u.role === "cliente" && u.status === "ATIVA");
  let owner = "";

  async function draw() {
    const list = await api(`/admin/beneficiaries${owner ? `?owner_id=${owner}` : ""}`);
    root.innerHTML = `
      ${pageHead("Beneficiários de clientes", "Contas de destino guardadas por cada cliente (no servidor, partilhadas entre a app do cliente e o balcão).",
        canManage ? `<button class="btn btn-primary" id="add">${icon("plus")} Registar beneficiário</button>` : "")}
      <div class="card">
        <div class="toolbar"><select class="select" id="owner" style="width:auto;min-width:240px" aria-label="Cliente"><option value="">Todos os clientes</option>
          ${clients.map((c) => `<option value="${esc(c.id)}" ${c.id === owner ? "selected" : ""}>${esc(c.full_name)}</option>`).join("")}</select>
          <span class="hint" style="margin-left:auto">${list.length} beneficiário(s)</span></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Cliente</th><th>Beneficiário</th><th>IBAN</th><th class="hide-sm">Registado por</th>${canManage ? "<th></th>" : ""}</tr></thead><tbody>
          ${list.map((b) => `<tr><td>${esc(b.owner_name)}</td><td>${esc(b.name)}${b.nickname ? `<div class="hint">${esc(b.nickname)}</div>` : ""}</td>
            <td class="mono">${esc(iban(b.iban))}</td>
            <td class="hide-sm">${esc(b.created_by === b.owner_id ? "o próprio cliente" : who(dir, b.created_by))}<div class="hint">${esc(dateTime(b.created_at))}</div></td>
            ${canManage ? `<td class="r"><button class="btn btn-ghost btn-icon" data-del="${esc(b.id)}" aria-label="Remover">${icon("trash")}</button></td>` : ""}</tr>`).join("")
          || `<tr><td colspan="5"><div class="empty">Sem beneficiários.</div></td></tr>`}
        </tbody></table></div>
      </div>`;
    $("#owner", root).addEventListener("change", (e) => { owner = e.target.value; draw(); });
    $("#add", root)?.addEventListener("click", add);
    $$("[data-del]", root).forEach((b) => b.addEventListener("click", async () => {
      const ben = list.find((x) => x.id === b.dataset.del);
      if (!(await confirmSheet({ title: "Remover beneficiário", message: `Remover ${esc(ben.name)} da lista de ${esc(ben.owner_name)}?`, confirm: "Remover", danger: true }))) return;
      try { await api(`/admin/beneficiaries/${ben.id}`, { method: "DELETE" }); toast("Beneficiário removido", "info"); draw(); }
      catch (ex) { toast(ex.message, "bad"); }
    }));
  }

  function add() {
    const s = sheet({
      title: "Registar beneficiário",
      body: `<div class="stack" style="gap:12px">
        <div class="field"><label for="b-owner">Cliente</label><select class="select" id="b-owner">${clients.map((c) => `<option value="${esc(c.id)}" ${c.id === owner ? "selected" : ""}>${esc(c.full_name)} · ${esc(c.email)}</option>`).join("")}</select></div>
        <div class="field"><label for="b-name">Nome do beneficiário</label><input class="input" id="b-name"></div>
        <div class="field"><label for="b-iban">IBAN</label><input class="input mono" id="b-iban" placeholder="GS-EU-00000000" spellcheck="false"></div>
        <div id="b-err"></div></div>`,
      footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="b-save">Guardar</button>`,
    });
    $("#b-save", s.el).addEventListener("click", async (e) => {
      const ib = $("#b-iban", s.el).value.trim().toUpperCase().replace(/\s/g, "").replace(/^GS-?(EU|AM)-?(\d{8})$/, "GS-$1-$2");
      if (!/^GS-(EU|AM)-\d{8}$/.test(ib)) return fieldError($("#b-iban", s.el), "IBAN inválido");
      busy(e.currentTarget, true);
      try {
        await api("/admin/beneficiaries", { method: "POST", body: { owner_id: $("#b-owner", s.el).value, name: $("#b-name", s.el).value.trim(), iban: ib } });
        toast("Beneficiário registado"); s.close(); draw();
      } catch (ex) {
        busy(e.currentTarget, false);
        $("#b-err", s.el).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
      }
    });
  }
  await draw();
}
