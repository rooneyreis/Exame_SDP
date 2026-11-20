// Limites institucionais (Administrador altera; Auditor/Operador consultam).
import { api } from "../api.js";
import { dateTime, number } from "../format.js";
import { icon } from "../icons.js";
import { $, busy, esc, fieldError, toast } from "../ui.js";
import { users, who } from "../staff.js";
import { pageHead } from "./common.js";

export async function render({ root, claims }) {
  const canManage = claims.role === "admin";
  const [rows, dir] = await Promise.all([api("/admin/settings"), users()]);
  const s = Object.fromEntries(rows.map((r) => [r.key, r]));
  root.innerHTML = `
    ${pageHead("Limites", "Aplicados pela API e, de forma definitiva, pelo coordenador de transações. Valores em EUR.")}
    <form class="card card-pad" id="limits" novalidate style="max-width:720px">
      <div class="stack" style="gap:18px">
        ${[["max_transfer_amount", "Montante máximo por transferência (EUR)", "Nenhuma transferência pode exceder este valor, convertido para a moeda da conta de origem."],
           ["approval_threshold", "Aprovação obrigatória a partir de", "Transferências registadas por operadores com montante igual ou superior ficam pendentes até um administrador as aprovar."],
           ["daily_limit_eur", "Limite diário por cliente (EUR)", "Soma do que cada cliente envia num dia a partir de todas as suas contas. Abrir mais contas não o aumenta; transferências entre contas próprias não contam."]]
          .map(([k, l, h]) => `<div class="field"><label for="${k}">${l}</label>
            <input class="input amount-input num" id="${k}" inputmode="decimal" value="${esc(number(s[k]?.value || 0))}" ${canManage ? "" : "readonly"}>
            <p class="hint">${h}${s[k]?.updated_by ? ` Última alteração: ${esc(who(dir, s[k].updated_by))}, ${esc(dateTime(s[k].updated_at))}.` : ""}</p></div>`).join("")}
        <div class="field"><label for="max_accounts_per_client">Máximo de contas ativas por cliente</label>
          <input class="input num" id="max_accounts_per_client" inputmode="numeric" style="max-width:160px" value="${esc(String(Math.round(Number(s.max_accounts_per_client?.value || 5))))}" ${canManage ? "" : "readonly"}>
          <p class="hint">Inclui os pedidos de abertura pendentes. Uma só conta por região e moeda.${s.max_accounts_per_client?.updated_by ? ` Última alteração: ${esc(who(dir, s.max_accounts_per_client.updated_by))}, ${esc(dateTime(s.max_accounts_per_client.updated_at))}.` : ""}</p></div>
        <p class="hint">${icon("info")} Os limites diários de cada conta são geridos em <a href="#/admin/accounts">Contas</a>. Todas as alterações ficam na auditoria com o valor anterior e o novo.</p>
        <div id="err"></div>
        ${canManage ? `<div><button class="btn btn-primary" type="submit">${icon("check")} Guardar limites</button></div>` : ""}
      </div>
    </form>`;
  if (!canManage) return;
  $("#limits", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const num = (id) => Number($(`#${id}`, root).value.replace(/\s/g, "").replace(/\./g, "").replace(",", "."));
    const max = num("max_transfer_amount"), thr = num("approval_threshold"), daily = num("daily_limit_eur");
    const maxAcc = Number($("#max_accounts_per_client", root).value.trim());
    let ok = true;
    fieldError($("#max_transfer_amount", root), max > 0 ? null : "Valor inválido"); ok &&= max > 0;
    fieldError($("#approval_threshold", root), thr > 0 && thr <= max ? null : "Tem de ser positivo e não superior ao máximo"); ok &&= thr > 0 && thr <= max;
    fieldError($("#daily_limit_eur", root), daily > 0 ? null : "Valor inválido"); ok &&= daily > 0;
    const accOk = Number.isInteger(maxAcc) && maxAcc >= 1 && maxAcc <= 20;
    fieldError($("#max_accounts_per_client", root), accOk ? null : "Entre 1 e 20"); ok &&= accOk;
    if (!ok) return;
    busy(e.submitter, true);
    try {
      await api("/admin/settings", { method: "PUT", body: { max_transfer_amount: max.toFixed(2), approval_threshold: thr.toFixed(2), daily_limit_eur: daily.toFixed(2), max_accounts_per_client: maxAcc } });
      toast("Limites atualizados — em vigor de imediato");
      render({ root, claims });
    } catch (ex) {
      busy(e.submitter, false);
      $("#err", root).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
    }
  });
}
