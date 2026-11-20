// Painel do Operador: o balcão.
//  [ fila KYC com aprovação direta (7)         ] [ atendimento: depósito / levantamento (5) ]
//  [ pedidos de transferência em curso (7)     ] [ regras em vigor + atalhos (5)            ]
import { api } from "../api.js";
import { dateTime, iban, initials, money, number, regionName, REGIONS } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, confirmSheet, esc, fieldError, toast } from "../ui.js";
import { requestChip } from "../staff.js";
import { cashSheet } from "./accounts.js";
import { pageHead } from "./common.js";

const IN_PROGRESS = ["PENDENTE_APROVACAO", "EM_EXECUCAO"];

export async function render({ root, navigate }) {
  const [mine, settings, pendingKyc, accountReqs] = await Promise.all([
    api("/transfer-requests?mine=true&limit=300"), api("/admin/settings"),
    api("/admin/users?status=PENDENTE_VERIFICACAO").catch(() => []),
    api("/admin/account-requests?status=PENDENTE").catch(() => []),
  ]);
  const lim = Object.fromEntries(settings.map((s) => [s.key, s.value]));
  const todayStr = new Date().toDateString();
  const today = mine.filter((r) => new Date(r.created_at).toDateString() === todayStr);
  const inProgress = mine.filter((r) => IN_PROGRESS.includes(r.effective_status));
  const recentDone = mine.filter((r) => !IN_PROGRESS.includes(r.effective_status)).slice(0, Math.max(0, 6 - inProgress.length));

  const kycRow = (u) => `
    <div class="queue-item" data-user="${esc(u.id)}">
      <span class="avatar" style="width:38px;height:38px;font-size:.8rem">${esc(initials(u.full_name))}</span>
      <span class="q-main"><b>${esc(u.full_name)}</b><span>${esc(u.email)} · <span class="region-tag" style="height:18px;min-width:28px;font-size:.62rem">${esc(u.region)}</span> conta em ${esc(REGIONS[u.region]?.currency || "")} · ${esc(dateTime(u.created_at))}</span></span>
      <span class="q-actions"><a class="btn btn-ghost btn-sm" href="#/ops/kyc" title="Ver dados do pedido">${icon("eye")}</a>
        <button class="btn btn-primary btn-sm" data-approve="${esc(u.id)}">${icon("check")} Aprovar</button></span>
    </div>`;

  const reqRow = (r) => `
    <button class="list-item" data-go="${esc(r.tx_id || "")}">
      <span class="tx-icon ${r.effective_status === "EXECUTADA" ? "in" : ["REJEITADA", "FALHADA"].includes(r.effective_status) ? "failed" : "out"}">${icon("transfer")}</span>
      <span class="grow"><span class="title">${esc(r.beneficiary_name || iban(r.to_iban))}</span>
        <span class="sub mono">${esc(iban(r.from_iban))} → ${esc(iban(r.to_iban))} · ${esc(dateTime(r.created_at))}</span></span>
      <span style="text-align:right"><span class="amount num">${esc(money(r.amount, r.currency))}</span><br>${requestChip(r.effective_status)}</span>
    </button>`;

  root.innerHTML = `
    ${pageHead("Balcão", `${pendingKyc.length} verificação(ões) pendente(s) · ${accountReqs.length} pedido(s) de contas · ${inProgress.length} transferência(s) em curso · ${today.length} registada(s) hoje`,
      `<a class="btn btn-primary" href="#/ops/transfer">${icon("plus")} Nova transferência</a>`)}
    <div class="bento">
      <section class="panel c-7">
        <div class="panel-head"><div><h3>Fila de verificação (KYC)</h3><div class="sub">aprovar abre a conta no centro de dados da região do cliente</div></div>
          <a class="link-btn" href="#/ops/kyc">Abrir fila completa</a></div>
        <div id="kyc-list">${pendingKyc.slice(0, 6).map(kycRow).join("") ||
          `<div class="empty-sm">${icon("check")} Nenhum pedido a aguardar verificação.</div>`}</div>
        <div class="panel-foot"><span>${pendingKyc.length > 6 ? `Mais ${pendingKyc.length - 6} na fila de KYC · ` : ""}${icon("bank")} ${accountReqs.length} pedido(s) de contas adicionais ou encerramento</span><a href="#/ops/account-requests">Decidir pedidos de contas</a></div>
      </section>
      <section class="panel c-5">
        <div class="panel-head"><div><h3>Atendimento ao balcão</h3><div class="sub">depósitos e levantamentos numa conta</div></div></div>
        <form class="panel-body desk" id="desk" novalidate>
          <div class="field"><label for="desk-iban">IBAN da conta</label>
            <div class="row"><input class="input mono" id="desk-iban" placeholder="GS-EU-00000001" spellcheck="false" autocomplete="off">
              <button class="btn btn-secondary" id="desk-find" type="submit">${icon("search")} Procurar</button></div></div>
          <div id="desk-account"><p class="hint">${icon("info")} Indique o IBAN do cliente para ver o saldo e registar a operação.</p></div>
          <div class="desk-ops">
            <button type="button" class="btn btn-secondary" id="desk-dep" disabled>${icon("deposit")} Depósito</button>
            <button type="button" class="btn btn-secondary" id="desk-wd" disabled>${icon("withdraw")} Levantamento</button>
          </div>
        </form>
      </section>
    </div>
    <div class="bento">
      <section class="panel c-7">
        <div class="panel-head"><div><h3>Pedidos de transferência</h3><div class="sub">${inProgress.length ? `${inProgress.length} em curso, seguidos dos mais recentes` : "nenhum em curso · os mais recentes"}</div></div>
          <a class="link-btn" href="#/ops/requests">Ver todos</a></div>
        <ul class="list">${[...inProgress, ...recentDone].slice(0, 8).map((r) => `<li>${reqRow(r)}</li>`).join("") ||
          `<div class="empty-sm">Ainda não registou transferências.</div>`}</ul>
      </section>
      <section class="panel c-5">
        <div class="panel-head"><h3>Regras em vigor</h3></div>
        <div class="panel-body">
          <dl class="kv"><dt>Máximo por transferência</dt><dd class="num">${esc(number(lim.max_transfer_amount))} EUR</dd>
            <dt>Exige aprovação a partir de</dt><dd class="num">${esc(number(lim.approval_threshold))}</dd>
            ${lim.daily_limit_eur ? `<dt>Limite diário por cliente</dt><dd class="num">${esc(number(lim.daily_limit_eur))} EUR</dd>` : ""}</dl>
          <p class="hint" style="margin-top:12px">${icon("info")} A partir do limiar, a transferência fica pendente até um administrador a aprovar (nunca quem a registou).</p>
        </div>
        <div class="panel-foot"><a href="#/ops/beneficiaries">Beneficiários</a><a href="#/ops/accounts">Contas</a><a href="#/ops/kyc">Abertura de contas</a></div>
      </section>
    </div>`;

  // --- KYC: aprovação direta a partir da fila ---
  $$("[data-approve]", root).forEach((b) => b.addEventListener("click", async () => {
    const row = b.closest(".queue-item");
    const name = $("b", row).textContent;
    if (!await confirmSheet({ title: "Aprovar verificação", message: `Confirmar a identidade de ${esc(name)} e abrir a conta?`, confirm: "Aprovar e abrir conta" })) return;
    busy(b, true, "A aprovar…");
    try {
      const r = await api(`/admin/users/${encodeURIComponent(b.dataset.approve)}/approve-kyc`, { method: "POST", body: {} });
      toast(`Conta ${r.account.iban} aberta em ${regionName(r.account.region)}`);
      row.remove();
      if (!$(".queue-item", root)) $("#kyc-list", root).innerHTML = `<div class="empty-sm">${icon("check")} Nenhum pedido a aguardar verificação.</div>`;
    } catch (ex) {
      busy(b, false);
      toast(ex.message, "bad");
    }
  }));

  // --- balcão: procurar a conta, depois depósito ou levantamento ---
  let account = null;
  const input = $("#desk-iban", root);
  async function find() {
    const v = input.value.trim().toUpperCase().replace(/\s/g, "");
    fieldError(input, null);
    try {
      account = await api(`/accounts/${encodeURIComponent(v)}`);
    } catch (ex) {
      account = null;
      fieldError(input, ex.status === 404 ? "Conta não encontrada" : ex.message);
    }
    $("#desk-account", root).innerHTML = account ? `
      <div class="desk-account"><span class="cur-badge">${esc(account.currency)}</span>
        <span><span class="mono">${esc(iban(account.iban))}</span><br><span class="hint">${esc(regionName(account.region))} · ${esc(account.status === "ATIVA" ? "ativa" : account.status.toLowerCase())}</span></span>
        <b class="num">${esc(money(account.balance, account.currency))}</b></div>` :
      `<p class="hint">${icon("info")} Indique o IBAN do cliente para ver o saldo e registar a operação.</p>`;
    const usable = !!account && account.status === "ATIVA";
    $("#desk-dep", root).disabled = !usable;
    $("#desk-wd", root).disabled = !usable;
  }
  $("#desk", root).addEventListener("submit", (e) => { e.preventDefault(); find(); });
  $("#desk-dep", root).addEventListener("click", () => account && cashSheet(account, "deposit", find));
  $("#desk-wd", root).addEventListener("click", () => account && cashSheet(account, "withdraw", find));

  $$("[data-go]", root).forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.go) navigate(`/tx/${encodeURIComponent(b.dataset.go)}`); else navigate("/ops/requests");
  }));
}
