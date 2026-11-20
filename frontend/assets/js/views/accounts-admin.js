// Todas as contas (Administrador gere limites e estado; Auditor/Operador consultam).
import { api } from "../api.js";
import { iban, money } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, esc, fieldError, sheet, toast } from "../ui.js";
import { downloadCsv, exportButtons, users, who } from "../staff.js";
import { pageHead } from "./common.js";

export async function render({ root, claims, navigate }) {
  const canManage = claims.role === "admin";
  const [accounts, dir] = await Promise.all([api("/admin/accounts"), users()]);
  let f = { region: "", status: "", q: "" };

  root.innerHTML = `
    ${pageHead("Contas", `${accounts.length} contas em duas regiões. ${canManage ? "Pode alterar o limite diário e bloquear contas." : "Consulta (só leitura)."}`, exportButtons())}
    <div class="card">
      <div class="toolbar">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="IBAN ou titular" aria-label="Pesquisar"></div>
        <select class="select" id="region" style="width:auto"><option value="">Todas as regiões</option><option value="EU">Europa</option><option value="AM">América</option></select>
        <select class="select" id="status" style="width:auto"><option value="">Todos os estados</option><option value="ATIVA">Ativas</option><option value="BLOQUEADA">Bloqueadas</option></select>
      </div>
      <div id="table"></div>
    </div>`;

  const filtered = () => accounts.filter((a) => (!f.region || a.region === f.region) && (!f.status || a.status === f.status) &&
    (!f.q || a.iban.includes(f.q.toUpperCase()) || who(dir, a.user_id).toLowerCase().includes(f.q.toLowerCase())));

  function draw() {
    const rows = filtered();
    $("#table", root).innerHTML = `<div class="table-wrap"><table class="table"><thead><tr><th>IBAN</th><th>Titular</th><th class="hide-sm">Região</th>
      <th class="r">Saldo</th><th class="r hide-sm">Limite diário</th><th>Estado</th>${canManage ? "<th></th>" : ""}</tr></thead><tbody>
      ${rows.map((a) => `<tr class="clickable" data-iban="${esc(a.iban)}">
        <td class="mono">${esc(iban(a.iban))}</td><td>${esc(who(dir, a.user_id))}</td>
        <td class="hide-sm">${a.region === "EU" ? "Europa" : "América"}</td>
        <td class="r num">${esc(money(a.balance, a.currency))}</td><td class="r num hide-sm">${esc(money(a.daily_limit, a.currency))}</td>
        <td><span class="chip ${a.status === "ATIVA" ? "status-done" : "status-failed"}">${a.status === "ATIVA" ? "Ativa" : "Bloqueada"}</span></td>
        ${canManage ? `<td class="r"><button class="btn btn-secondary btn-sm" data-edit="${esc(a.iban)}">${icon("settings")} Gerir</button></td>` : ""}
      </tr>`).join("") || `<tr><td colspan="7"><div class="empty">Sem resultados.</div></td></tr>`}</tbody></table></div>`;
    $$("[data-iban]", root).forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("button")) navigate(`/accounts/${encodeURIComponent(tr.dataset.iban)}`); }));
    $$("[data-edit]", root).forEach((b) => b.addEventListener("click", () => edit(accounts.find((a) => a.iban === b.dataset.edit))));
  }

  function edit(acc) {
    const s = sheet({
      title: "Gerir conta",
      body: `<p class="soft" style="margin-bottom:14px"><span class="mono">${esc(iban(acc.iban))}</span> · ${esc(who(dir, acc.user_id))}</p>
        <div class="field"><label for="limit">Limite diário de transferências (${esc(acc.currency)})</label>
          <input class="input num" id="limit" inputmode="decimal" value="${esc(acc.daily_limit)}"></div>
        <div class="field" style="margin-top:14px"><span class="label">Estado</span>
          <div class="segmented" role="group"><button data-st="ATIVA" aria-pressed="${acc.status === "ATIVA"}">Ativa</button><button data-st="BLOQUEADA" aria-pressed="${acc.status === "BLOQUEADA"}">Bloqueada</button></div>
          <p class="hint">Uma conta bloqueada não envia nem recebe transferências (as operações são recusadas pelo banco da região).</p></div>
        <div id="acc-err"></div>`,
      footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="save">Guardar alterações</button>`,
    });
    let st = acc.status;
    $$("[data-st]", s.el).forEach((b) => b.addEventListener("click", () => { st = b.dataset.st; $$("[data-st]", s.el).forEach((x) => x.setAttribute("aria-pressed", String(x === b))); }));
    $("#save", s.el).addEventListener("click", async (e) => {
      const limit = Number($("#limit", s.el).value.replace(",", "."));
      if (!(limit > 0)) return fieldError($("#limit", s.el), "Limite inválido");
      busy(e.currentTarget, true);
      try {
        const updated = await api(`/admin/accounts/${encodeURIComponent(acc.iban)}`, { method: "PATCH", body: { daily_limit: limit.toFixed(2), status: st } });
        Object.assign(acc, updated);
        toast("Conta atualizada");
        s.close(); draw();
      } catch (ex) {
        busy(e.currentTarget, false);
        $("#acc-err", s.el).innerHTML = `<div class="banner banner-bad" style="margin-top:12px">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
      }
    });
  }

  $("#q", root).addEventListener("input", (e) => { f.q = e.target.value.trim(); draw(); });
  $("#region", root).addEventListener("change", (e) => { f.region = e.target.value; draw(); });
  $("#status", root).addEventListener("change", (e) => { f.status = e.target.value; draw(); });
  root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv("contas.csv",
    ["iban", "titular", "regiao", "moeda", "saldo", "limite_diario", "estado", "aberta_em"],
    filtered().map((a) => [a.iban, who(dir, a.user_id), a.region, a.currency, a.balance, a.daily_limit, a.status, a.created_at])));
  draw();
}
