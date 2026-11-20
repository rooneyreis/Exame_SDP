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
  const f = { q: "", region: "all" };
  function draw() {
    const all = beneficiaries.all();
    const q = f.q.toLowerCase();
    const list = all.filter((b) => (f.region === "all" || regionOf(b.iban) === f.region) &&
      (!q || [b.name, b.iban, b.nickname].some((v) => (v || "").toLowerCase().includes(q))))
      .sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0) || a.name.localeCompare(b.name));
    root.innerHTML = `
      ${pageHead("Beneficiários", "Contas para onde transfere com frequência, guardadas na sua conta.", `<button class="btn btn-primary" id="add">${icon("plus")} Novo beneficiário</button>`)}
      <section class="panel"><div class="metric-strip" style="--n:4">
        <div class="metric"><span class="m-label">${icon("users")} Guardados</span><span class="m-value">${all.length}</span></div>
        <div class="metric"><span class="m-label">${icon("star")} Favoritos</span><span class="m-value">${all.filter((b) => b.favorite).length}</span></div>
        <div class="metric"><span class="m-label">${icon("globe")} Europa</span><span class="m-value">${all.filter((b) => regionOf(b.iban) === "EU").length}</span><span class="m-sub">contas GS-EU</span></div>
        <div class="metric"><span class="m-label">${icon("globe")} América</span><span class="m-value">${all.filter((b) => regionOf(b.iban) === "AM").length}</span><span class="m-sub">contas GS-AM</span></div>
      </div></section>
      <section class="panel mt">
        <div class="filters">
          <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Nome, IBAN ou alcunha" value="${esc(f.q)}" aria-label="Pesquisar beneficiários"></div>
          <span class="grow"></span>
          ${[["all", "Todos"], ["EU", "Europa"], ["AM", "América"]].map(([k, l]) => `<button class="chip-filter" data-region="${k}" aria-pressed="${k === f.region}">${l}</button>`).join("")}
        </div>
        <div class="panel-body" style="padding-top:20px">
        ${all.length ? `<div class="tile-grid">${list.map((b) => {
          const r = REGIONS[regionOf(b.iban)];
          return `<div class="tile">
            <div class="tile-top"><span class="avatar" style="width:42px;height:42px">${esc(initials(b.name))}</span>
              <span class="grow"><span class="name">${esc(b.name)}</span><span class="meta" style="display:block">${esc(b.nickname || r?.name || "")}</span></span>
              ${b.favorite ? `<span style="color:var(--gold)" title="Favorito">${icon("star")}</span>` : ""}</div>
            <div class="mono meta">${esc(fmtIban(b.iban))}<br>${esc(r?.name || "")} · ${esc(r?.city || "")}</div>
            <div class="tile-actions">
              <a class="btn btn-primary btn-sm" style="flex:1" href="#/transfer?to=${encodeURIComponent(b.iban)}&name=${encodeURIComponent(b.name)}">${icon("arrowUp")} Transferir</a>
              <button class="btn btn-secondary btn-icon btn-sm" data-edit="${esc(b.id)}" aria-label="Editar ${esc(b.name)}" title="Editar">${icon("settings")}</button>
              <button class="btn btn-secondary btn-icon btn-sm" data-del="${esc(b.id)}" aria-label="Remover ${esc(b.name)}" title="Remover">${icon("trash")}</button>
            </div></div>`;
        }).join("")}<button class="tile add" id="add-tile">${icon("plus")}<span>Adicionar beneficiário</span></button></div>
          ${!list.length ? `<div class="empty-sm">Nenhum beneficiário corresponde à pesquisa.</div>` : ""}`
        : `<div class="empty"><div class="tx-icon">${icon("users")}</div><h3>Ainda não tem beneficiários</h3>
            <p>Adicione as contas para onde transfere com frequência e envie dinheiro em segundos.</p>
            <button class="btn btn-primary" id="add-empty" style="margin-top:16px">${icon("plus")} Adicionar beneficiário</button></div>`}
        </div>
      </section>`;
    ["#add", "#add-empty", "#add-tile"].forEach((id) => $(id, root)?.addEventListener("click", () => editSheet(null, draw)));
    let t;
    $("#q", root).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value; draw(); const i = $("#q", root); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); });
    $$("[data-region]", root).forEach((b) => b.addEventListener("click", () => { f.region = b.dataset.region; draw(); }));
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
