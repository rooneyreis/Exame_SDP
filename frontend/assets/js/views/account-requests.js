// Pedidos de contas: abertura e encerramento pedidos pelos clientes, decididos por um
// operador (aprovar / rejeitar com motivo), e abertura direta de conta ao balcão.
// Administrador e auditor consultam (só leitura).
import { api } from "../api.js";
import { CURRENCY_NAMES, dateTime, iban, REGION_CODES, REGIONS, regionName } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, confirmSheet, drawer, esc, toast } from "../ui.js";
import { users, who } from "../staff.js";
import { pageHead } from "./common.js";

const STATUS = { PENDENTE: ["status-pending", "clock", "Pendente"], APROVADO: ["status-done", "check", "Aprovado"], REJEITADO: ["status-failed", "x", "Rejeitado"] };
const CURRENCIES = ["EUR", "USD", "MZN"];

export async function render({ root, claims }) {
  const canDecide = claims.role === "operador";
  const f = { status: "PENDENTE", kind: "" };

  async function draw() {
    const [rows, dir] = await Promise.all([
      api(`/admin/account-requests${f.status ? `?status=${f.status}` : ""}`), users({ fresh: true }),
    ]);
    const list = rows.filter((r) => !f.kind || r.kind === f.kind);
    const pendingAll = f.status === "PENDENTE" ? rows : null;
    root.innerHTML = `
      ${pageHead("Pedidos de contas", "Abertura de contas adicionais (noutra região ou moeda) e encerramentos pedidos pelos clientes.",
        canDecide ? `<button class="btn btn-primary" id="desk-open">${icon("plus")} Abrir conta ao balcão</button>` : "")}
      ${pendingAll ? `<section class="panel"><div class="metric-strip" style="--n:3">
        <div class="metric"><span class="m-label">${icon("clock")} Pendentes</span><span class="m-value">${pendingAll.length}</span><span class="m-sub">a aguardar decisão</span></div>
        <div class="metric"><span class="m-label">${icon("plus")} Aberturas</span><span class="m-value">${pendingAll.filter((r) => r.kind === "ABERTURA").length}</span><span class="m-sub">nova conta noutra região ou moeda</span></div>
        <div class="metric"><span class="m-label">${icon("x")} Encerramentos</span><span class="m-value">${pendingAll.filter((r) => r.kind === "ENCERRAMENTO").length}</span><span class="m-sub">só com saldo 0</span></div>
      </div></section>` : ""}
      <section class="panel ${pendingAll ? "mt" : ""}">
        <div class="filters">
          ${[["PENDENTE", "Pendentes"], ["APROVADO", "Aprovados"], ["REJEITADO", "Rejeitados"], ["", "Todos"]].map(([k, l]) => `<button class="chip-filter" data-status="${k}" aria-pressed="${k === f.status}">${l}</button>`).join("")}
          <span class="grow"></span>
          ${[["", "Todos os tipos"], ["ABERTURA", "Abertura"], ["ENCERRAMENTO", "Encerramento"]].map(([k, l]) => `<button class="chip-filter" data-kind="${k}" aria-pressed="${k === f.kind}">${l}</button>`).join("")}
        </div>
        ${list.length ? `<div class="table-wrap"><table class="table">
          <thead><tr><th class="w-date">Pedido</th><th>Cliente</th><th class="w-status">Tipo</th><th>Conta</th><th class="w-status">Estado</th>${canDecide ? `<th class="w-actions"></th>` : ""}</tr></thead>
          <tbody>${list.map((r) => {
            const [cls, ic, label] = STATUS[r.status] || ["", "clock", r.status];
            return `<tr>
              <td class="w-date num">${esc(dateTime(r.created_at))}${r.created_by_role !== "cliente" ? `<div class="cell-sub">ao balcão</div>` : ""}</td>
              <td><span class="cell-main">${esc(who(dir, r.user_id))}</span><div class="cell-sub">${esc(dir.get(r.user_id)?.email || "")}</div></td>
              <td class="w-status"><span class="chip ${r.kind === "ABERTURA" ? "chip-accent" : ""}">${r.kind === "ABERTURA" ? "Abertura" : "Encerramento"}</span></td>
              <td><span class="region-tag">${esc(r.region)}</span> <b>${esc(r.currency)}</b> <span class="soft">· ${esc(REGIONS[r.region]?.city || "")}</span>
                ${r.iban ? `<div class="cell-sub mono">${esc(iban(r.iban))}</div>` : ""}</td>
              <td class="w-status"><span class="chip ${cls}">${icon(ic)}${label}</span>
                ${r.status !== "PENDENTE" ? `<div class="cell-sub">${esc(who(dir, r.decided_by))}${r.decision_reason ? ` · ${esc(r.decision_reason)}` : ""}</div>` : ""}</td>
              ${canDecide ? `<td class="w-actions">${r.status === "PENDENTE" ? `<div class="row" style="gap:6px;justify-content:flex-end">
                <button class="btn btn-secondary btn-sm" data-reject="${esc(r.id)}">Rejeitar</button>
                <button class="btn btn-primary btn-sm" data-approve="${esc(r.id)}">${icon("check")} Aprovar</button></div>` : ""}</td>` : ""}
            </tr>`; }).join("")}</tbody></table></div>`
          : `<div class="empty"><div class="tx-icon in">${icon("check")}</div><h3>Sem pedidos ${f.status === "PENDENTE" ? "pendentes" : "neste filtro"}</h3></div>`}
      </section>`;

    $$("[data-status]", root).forEach((b) => b.addEventListener("click", () => { f.status = b.dataset.status; draw(); }));
    $$("[data-kind]", root).forEach((b) => b.addEventListener("click", () => { f.kind = b.dataset.kind; draw(); }));
    $("#desk-open", root)?.addEventListener("click", () => deskOpen(dir, draw));

    $$("[data-approve]", root).forEach((b) => b.addEventListener("click", async () => {
      const r = rows.find((x) => x.id === b.dataset.approve);
      const what = r.kind === "ABERTURA"
        ? `Abrir uma conta ${r.currency} em ${REGIONS[r.region]?.city} para ${who(dir, r.user_id)}? A conta é criada no centro de dados de ${regionName(r.region)}.`
        : `Encerrar a conta ${iban(r.iban)} de ${who(dir, r.user_id)}? Só é possível com saldo 0 e sem transações em curso.`;
      if (!await confirmSheet({ title: r.kind === "ABERTURA" ? "Aprovar abertura" : "Confirmar encerramento", message: esc(what), confirm: "Aprovar", danger: r.kind !== "ABERTURA" })) return;
      busy(b, true, "A aprovar…");
      try {
        const out = await api(`/admin/account-requests/${encodeURIComponent(r.id)}/approve`, { method: "POST" });
        toast(r.kind === "ABERTURA" ? `Conta ${out.account.iban} aberta` : `Conta ${out.account.iban} encerrada`);
        draw();
      } catch (ex) {
        busy(b, false);
        toast(ex.message, "bad");
      }
    }));

    $$("[data-reject]", root).forEach((b) => b.addEventListener("click", () => {
      const r = rows.find((x) => x.id === b.dataset.reject);
      const d = drawer({
        title: "Rejeitar pedido", subtitle: `${r.kind === "ABERTURA" ? "Abertura" : "Encerramento"} · ${r.region} · ${r.currency} · ${who(dir, r.user_id)}`,
        body: `<div class="field"><label for="reason">Motivo (o cliente vê este texto)</label>
          <textarea class="input" id="reason" rows="4" maxlength="200" placeholder="Ex.: documentação de residência em falta"></textarea></div>
          <div id="rej-err"></div>`,
        footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-danger" id="rej-ok">${icon("x")} Rejeitar pedido</button>`,
      });
      setTimeout(() => $("#reason", d.el).focus(), 50);
      $("#rej-ok", d.el).addEventListener("click", async (e) => {
        const reason = $("#reason", d.el).value.trim();
        if (reason.length < 3) { $("#rej-err", d.el).innerHTML = `<p class="error-text">${icon("alert")}Indique o motivo da rejeição.</p>`; return; }
        busy(e.currentTarget, true, "A rejeitar…");
        try {
          await api(`/admin/account-requests/${encodeURIComponent(r.id)}/reject`, { method: "POST", body: { reason } });
          d.close(); toast("Pedido rejeitado", "info"); draw();
        } catch (ex) {
          busy(e.currentTarget, false);
          $("#rej-err", d.el).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
        }
      });
    }));
  }
  await draw();
}

/** Abertura direta ao balcão: escolher um cliente ativo, a região e a moeda. */
function deskOpen(dir, onDone) {
  const clients = [...dir.values()].filter((u) => u.role === "cliente" && u.status === "ATIVA").sort((a, b) => a.full_name.localeCompare(b.full_name));
  const sel = { user: null, region: null, currency: null };
  const d = drawer({
    title: "Abrir conta ao balcão", subtitle: "A conta fica ativa de imediato e o registo fica na auditoria.", wide: true,
    body: `
      <div class="field"><label for="cq">Cliente</label>
        <div class="search">${icon("search")}<input class="input" id="cq" type="search" placeholder="Nome ou email" autocomplete="off"></div>
        <div class="rows" id="clist" style="max-height:220px;overflow:auto;border:1px solid var(--line);border-radius:12px;margin-top:8px"></div></div>
      <div class="field" style="margin-top:16px"><span class="label">Região</span>
        <div class="segmented" role="group" aria-label="Região">${REGION_CODES.map((r) => `<button type="button" data-r="${r}" aria-pressed="false">${esc(REGIONS[r].name)} · ${esc(REGIONS[r].city)}</button>`).join("")}</div></div>
      <div class="field" style="margin-top:16px"><span class="label">Moeda</span>
        <div class="segmented" role="group" aria-label="Moeda">${CURRENCIES.map((c) => `<button type="button" data-c="${c}" aria-pressed="false">${c} · ${esc(CURRENCY_NAMES[c])}</button>`).join("")}</div></div>
      <div id="desk-err" style="margin-top:12px"></div>`,
    footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="desk-ok" disabled>${icon("check")} Abrir conta</button>`,
  });
  const el = d.el;
  function drawClients(q = "") {
    const s = q.toLowerCase();
    const shown = clients.filter((u) => !s || [u.full_name, u.email].some((v) => (v || "").toLowerCase().includes(s))).slice(0, 30);
    $("#clist", el).innerHTML = shown.map((u) => `
      <button type="button" class="r-item" data-u="${esc(u.id)}" style="width:100%;text-align:left;border:0;background:${sel.user === u.id ? "var(--accent-soft)" : "none"}">
        <span class="avatar" style="width:32px;height:32px;font-size:.72rem">${esc(u.full_name.split(" ").map((p) => p[0]).slice(0, 2).join(""))}</span>
        <span style="min-width:0"><span class="r-title">${esc(u.full_name)}</span><span class="r-sub">${esc(u.email)} · registo ${esc(u.region)}</span></span>
        <span class="r-end">${sel.user === u.id ? icon("check") : ""}</span></button>`).join("") || `<div class="empty-sm">Nenhum cliente ativo encontrado.</div>`;
    $$("[data-u]", el).forEach((b) => b.addEventListener("click", () => { sel.user = b.dataset.u; drawClients($("#cq", el).value); refresh(); }));
  }
  function refresh() {
    $$("[data-r]", el).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.r === sel.region)));
    $$("[data-c]", el).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.c === sel.currency)));
    $("#desk-ok", el).disabled = !(sel.user && sel.region && sel.currency);
  }
  $("#cq", el).addEventListener("input", (e) => drawClients(e.target.value));
  $$("[data-r]", el).forEach((b) => b.addEventListener("click", () => { sel.region = b.dataset.r; sel.currency ||= REGIONS[sel.region].currency; refresh(); }));
  $$("[data-c]", el).forEach((b) => b.addEventListener("click", () => { sel.currency = b.dataset.c; refresh(); }));
  $("#desk-ok", el).addEventListener("click", async (e) => {
    busy(e.currentTarget, true, "A abrir…");
    try {
      const acc = await api("/admin/accounts", { method: "POST", body: { user_id: sel.user, region: sel.region, currency: sel.currency } });
      d.close();
      toast(`Conta ${acc.iban} aberta para ${who(dir, sel.user)}`);
      onDone();
    } catch (ex) {
      busy(e.currentTarget, false);
      $("#desk-err", el).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
    }
  });
  drawClients();
  refresh();
}
