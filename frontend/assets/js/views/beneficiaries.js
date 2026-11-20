import { iban as fmtIban, initials, REGIONS, regionOf } from "../format.js";
import { icon } from "../icons.js";
import { beneficiaries } from "../store.js";
import { $, $$, confirmSheet, esc, fieldError, sheet, toast } from "../ui.js";
import { pageHead } from "./common.js";

function editSheet(existing, onSave) {
  const s = sheet({
    title: existing ? "Editar beneficiário" : "Novo beneficiário",
    body: `<div class="stack" style="gap:14px">
      <div class="field"><label for="b-name">Nome</label><input class="input" id="b-name" value="${esc(existing?.name || "")}" placeholder="Nome completo"></div>
      <div class="field"><label for="b-iban">IBAN</label><input class="input mono" id="b-iban" value="${esc(existing?.iban || "")}" placeholder="GS-EU-00000000" ${existing ? "readonly" : ""} spellcheck="false"></div>
      <div class="field"><label for="b-nick">Alcunha <span class="muted">(opcional)</span></label><input class="input" id="b-nick" value="${esc(existing?.nickname || "")}" placeholder="Ex.: Senhorio"></div>
      <label class="row" style="gap:10px;font-size:.88rem"><input type="checkbox" id="b-fav" ${existing?.favorite ? "checked" : ""} style="width:18px;height:18px;accent-color:var(--accent)"> Marcar como favorito</label>
      <p class="hint">${icon("lock")} Guardados na sua conta: disponíveis em qualquer dispositivo e ao balcão.</p></div>`,
    footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="b-ok">Guardar</button>`,
  });
  $("#b-ok", s.el).addEventListener("click", async () => {
    const name = $("#b-name", s.el).value.trim();
    const ib = $("#b-iban", s.el).value.trim().toUpperCase().replace(/\s/g, "").replace(/^GS-?(EU|AM)-?(\d{8})$/, "GS-$1-$2");
    let ok = true;
    fieldError($("#b-name", s.el), name.length >= 2 ? null : "Indique o nome"); ok &&= name.length >= 2;
    const validIban = /^GS-(EU|AM)-\d{8}$/.test(ib);
    fieldError($("#b-iban", s.el), validIban ? null : "IBAN inválido (GS-EU-######## ou GS-AM-########)"); ok &&= validIban;
    if (!ok) return;
    try {
      await beneficiaries.save({ ...(existing || {}), name, iban: ib, nickname: $("#b-nick", s.el).value.trim(), favorite: $("#b-fav", s.el).checked });
    } catch (ex) {
      return fieldError($("#b-iban", s.el), ex.message);
    }
    toast(existing ? "Beneficiário atualizado" : "Beneficiário adicionado");
    s.close();
    onSave();
  });
}

export async function render({ root }) {
  await beneficiaries.load({ fresh: true });
  function draw() {
    const list = beneficiaries.all();
    root.innerHTML = `
      ${pageHead("Beneficiários", "Contas para onde transfere com frequência.", `<button class="btn btn-primary" id="add">${icon("plus")} Novo beneficiário</button>`)}
      ${list.length ? `<div class="card"><ul class="list">${list.map((b) => {
        const r = REGIONS[regionOf(b.iban)];
        return `<li class="list-item">
          <span class="avatar">${esc(initials(b.name))}</span>
          <span class="grow"><span class="title">${esc(b.name)} ${b.favorite ? `<span style="color:var(--gold)">${icon("star")}</span>` : ""}</span>
            <span class="sub"><span class="mono">${esc(fmtIban(b.iban))}</span> · ${esc(r?.name || "")}${b.nickname ? ` · ${esc(b.nickname)}` : ""}</span></span>
          <span class="row" style="gap:4px">
            <a class="btn btn-primary btn-sm" href="#/transfer?to=${encodeURIComponent(b.iban)}&name=${encodeURIComponent(b.name)}">${icon("arrowUp")}<span class="hide-sm">Transferir</span></a>
            <button class="btn btn-ghost btn-icon" data-edit="${esc(b.id)}" aria-label="Editar">${icon("settings")}</button>
            <button class="btn btn-ghost btn-icon" data-del="${esc(b.id)}" aria-label="Remover">${icon("trash")}</button>
          </span></li>`;
      }).join("")}</ul></div>`
      : `<div class="card"><div class="empty"><div class="tx-icon">${icon("users")}</div><h3>Ainda não tem beneficiários</h3>
          <p>Adicione as contas para onde transfere com frequência e envie dinheiro em segundos.</p>
          <button class="btn btn-primary" id="add-empty" style="margin-top:16px">${icon("plus")} Adicionar beneficiário</button></div></div>`}`;
    $("#add", root)?.addEventListener("click", () => editSheet(null, draw));
    $("#add-empty", root)?.addEventListener("click", () => editSheet(null, draw));
    $$("[data-edit]", root).forEach((b) => b.addEventListener("click", () => editSheet(beneficiaries.get(b.dataset.edit), draw)));
    $$("[data-del]", root).forEach((b) => b.addEventListener("click", async () => {
      const ben = beneficiaries.get(b.dataset.del);
      if (await confirmSheet({ title: "Remover beneficiário", message: `Remover ${esc(ben.name)} da sua lista? Pode voltar a adicioná-lo mais tarde.`, confirm: "Remover", danger: true })) {
        await beneficiaries.remove(ben.id);
        toast("Beneficiário removido", "info");
        draw();
      }
    }));
  }
  draw();
}
