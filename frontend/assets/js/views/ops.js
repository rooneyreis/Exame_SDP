import { api } from "../api.js";
import { date, dateTime, initials, REGIONS, roleLabel } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, esc, fieldError, sheet, toast } from "../ui.js";
import { pageHead } from "./common.js";

export async function render(ctx) {
  if (ctx.path === "/ops/accounts") return accountsLookup(ctx);   // /ops/kyc -> abertura de contas
  return kyc(ctx);
}

async function kyc({ root, claims }) {
  const canApprove = claims.role === "operador";
  let tab = "pending";
  async function draw() {
    const users = await api(tab === "pending" ? "/admin/users?status=PENDENTE_VERIFICACAO" : "/admin/users");
    const rows = tab === "pending" ? users : users.filter((u) => u.role === "cliente");
    root.innerHTML = `
      ${pageHead("Abertura de contas", "Verificação de identidade (KYC) dos novos clientes. A aprovação abre a conta no centro de dados da região do cliente.")}
      <div class="grid g-3" style="margin-bottom:20px">
        <div class="card card-pad stat"><div class="label">${icon("clock")} A aguardar verificação</div><div class="value num" id="n-pending">${tab === "pending" ? rows.length : "—"}</div></div>
        <div class="card card-pad stat"><div class="label">${icon("globe")} Europa · Lisboa</div><div class="value num">${rows.filter((u) => u.region === "EU").length}</div><div class="delta">${tab === "pending" ? "pedidos pendentes" : "clientes"}</div></div>
        <div class="card card-pad stat"><div class="label">${icon("globe")} América · Nova Iorque</div><div class="value num">${rows.filter((u) => u.region === "AM").length}</div><div class="delta">${tab === "pending" ? "pedidos pendentes" : "clientes"}</div></div>
      </div>
      <div class="card">
        <div class="toolbar"><div class="segmented" role="group">
          <button data-tab="pending" aria-pressed="${tab === "pending"}">Pendentes</button><button data-tab="all" aria-pressed="${tab === "all"}">Todos os clientes</button></div></div>
        ${rows.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Cliente</th><th class="hide-sm">Contacto</th><th>Região</th><th class="hide-sm">Pedido</th><th>Estado</th><th></th></tr></thead><tbody>
          ${rows.map((u) => `<tr class="clickable" data-user="${esc(u.id)}">
            <td><div class="row"><span class="avatar">${esc(initials(u.full_name))}</span><b style="font-weight:560">${esc(u.full_name)}</b></div></td>
            <td class="hide-sm"><div>${esc(u.email)}</div><div class="hint">${esc(u.phone)}</div></td>
            <td>${esc(REGIONS[u.region]?.name)}</td>
            <td class="hide-sm">${esc(date(u.created_at))}</td>
            <td><span class="chip ${u.status === "ATIVA" ? "status-done" : u.status === "BLOQUEADA" ? "status-failed" : "status-pending"}">${esc(u.status === "PENDENTE_VERIFICACAO" ? "Pendente" : u.status === "ATIVA" ? "Ativa" : "Bloqueada")}</span></td>
            <td class="r">${icon("chevronRight")}</td></tr>`).join("")}
          </tbody></table></div>`
        : `<div class="empty"><div class="tx-icon in">${icon("check")}</div><h3>Sem pedidos pendentes</h3><p>Todos os pedidos de abertura de conta foram tratados.</p></div>`}
      </div>`;
    $$("[data-tab]", root).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; draw(); }));
    $$("[data-user]", root).forEach((tr) => tr.addEventListener("click", () => review(tr.dataset.user)));
  }

  async function review(id) {
    const u = await api(`/admin/users/${encodeURIComponent(id)}`);
    const pending = u.status === "PENDENTE_VERIFICACAO";
    const s = sheet({
      title: pending ? "Verificar identidade" : "Cliente",
      body: `
        <div class="row" style="gap:14px;margin-bottom:12px"><span class="avatar" style="width:48px;height:48px">${esc(initials(u.full_name))}</span>
          <div><h3>${esc(u.full_name)}</h3><p class="hint">${esc(roleLabel(u.role))} · desde ${esc(dateTime(u.created_at))}</p></div></div>
        <dl class="kv">
          <dt>Email</dt><dd>${esc(u.email)}</dd><dt>Telemóvel</dt><dd>${esc(u.phone)}</dd>
          <dt>Documento</dt><dd class="mono">${esc(u.document_id || "—")}</dd>
          <dt>Data de nascimento</dt><dd>${esc(u.birth_date ? date(u.birth_date) : "—")}</dd>
          <dt>Região</dt><dd>${esc(REGIONS[u.region]?.name)}</dd>
        </dl>
        <p class="hint" style="margin-top:10px">${icon("lock")} Documento e data de nascimento estão cifrados na base de dados (AES-256-GCM) e só são decifrados para esta consulta.</p>
        ${pending && canApprove ? `<div class="field" style="margin-top:16px"><label for="cur">Moeda da conta a abrir</label>
          <select class="select" id="cur">${["EUR", "USD", "MZN"].map((c) => `<option ${c === REGIONS[u.region].currency ? "selected" : ""}>${c}</option>`).join("")}</select></div>
          <div id="kyc-err"></div>` : ""}`,
      footer: pending && canApprove
        ? `<button class="btn btn-secondary" data-close>Fechar</button><button class="btn btn-primary" id="approve">${icon("check")} Aprovar e abrir conta</button>`
        : `<button class="btn btn-secondary" data-close>Fechar</button>`,
    });
    $("#approve", s.el)?.addEventListener("click", async (ev) => {
      busy(ev.currentTarget, true, "A abrir conta…");
      try {
        const r = await api(`/admin/users/${encodeURIComponent(id)}/approve-kyc`, { method: "POST", body: { currency: $("#cur", s.el).value } });
        toast(`Conta ${r.account.iban} aberta em ${REGIONS[r.account.region].name}`);
        s.close();
        draw();
      } catch (ex) {
        busy(ev.currentTarget, false);
        $("#kyc-err", s.el).innerHTML = `<div class="banner banner-bad" style="margin-top:12px">${icon("alert")}<span>${esc(ex.status === 503 ? "O serviço de contas está indisponível. O pedido continua pendente; tente novamente." : ex.message)}</span></div>`;
      }
    });
  }
  await draw();
}

const RECENT = "gs.staff.recentIbans";

function recent() {
  try { return JSON.parse(localStorage.getItem(RECENT)) || []; } catch { return []; }
}

async function accountsLookup({ root, navigate }) {
  root.innerHTML = `
    ${pageHead("Contas de clientes", "Consulte qualquer conta pelo IBAN. O IBAN indica a região: GS-EU (Lisboa) ou GS-AM (Nova Iorque).")}
    <form class="card card-pad" id="lookup" novalidate style="max-width:640px">
      <div class="field"><label for="ib">IBAN</label>
        <div class="row"><input class="input mono" id="ib" placeholder="GS-EU-00000001" spellcheck="false" autocomplete="off">
          <button class="btn btn-primary" type="submit">${icon("search")} Consultar</button></div></div>
      ${recent().length ? `<p class="label" style="margin-top:18px">Consultas recentes</p><div class="row wrap" style="gap:8px;margin-top:8px">
        ${recent().map((i) => `<a class="chip chip-outline mono" href="#/accounts/${encodeURIComponent(i)}">${esc(i)}</a>`).join("")}</div>` : ""}
    </form>`;
  $("#lookup", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#ib", root);
    const v = input.value.trim().toUpperCase().replace(/\s/g, "").replace(/^GS-?(EU|AM)-?(\d{8})$/, "GS-$1-$2");
    if (!/^GS-(EU|AM)-\d{8}$/.test(v)) return fieldError(input, "IBAN inválido");
    try {
      await api(`/accounts/${encodeURIComponent(v)}`);
      localStorage.setItem(RECENT, JSON.stringify([v, ...recent().filter((x) => x !== v)].slice(0, 8)));
      navigate(`/accounts/${encodeURIComponent(v)}`);
    } catch (ex) {
      fieldError(input, ex.status === 404 ? "Conta não encontrada" : ex.message);
    }
  });
}
