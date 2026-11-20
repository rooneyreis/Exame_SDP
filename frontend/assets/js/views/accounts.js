import { api } from "../api.js";
import { areaChart } from "../chart.js";
import { balanceSeries, movements, myAccounts } from "../data.js";
import { date, dateTime, iban, money, originLabel, REGIONS } from "../format.js";
import { icon } from "../icons.js";
import { $, bindCopy, busy, esc, fieldError, sheet, toast } from "../ui.js";
import { accountCard, masked, pageHead } from "./common.js";

export async function render({ root, params, claims, navigate }) {
  if (!params.iban) return list(root);
  return detail(root, params.iban, claims, navigate);
}

async function list(root) {
  const accounts = await myAccounts();
  root.innerHTML = `
    ${pageHead("Contas", "As suas contas à ordem e respetivos dados bancários.")}
    <div class="grid g-3">${accounts.map((a) => accountCard(a)).join("")}</div>
    <div class="card card-pad" style="margin-top:24px">
      <div class="row" style="align-items:flex-start;gap:14px">
        <span class="tx-icon">${icon("info")}</span>
        <div><h3>Precisa de outra moeda?</h3><p class="soft" style="margin-top:4px">As contas em EUR, USD e MZN são abertas por um operador após verificação. Contacte o seu gestor de conta.</p></div>
      </div>
    </div>`;
}

export function cashSheet(account, kind, onDone) {
  const isDeposit = kind === "deposit";
  const s = sheet({
    title: isDeposit ? "Registar depósito" : "Registar levantamento",
    body: `<p class="soft" style="margin-bottom:16px">Conta <span class="mono">${esc(iban(account.iban))}</span> · saldo ${esc(money(account.balance, account.currency))}</p>
      <div class="field"><label for="cash-amount">Montante</label>
        <div class="input-affix"><input class="input amount-input num" id="cash-amount" inputmode="decimal" placeholder="0,00"><span class="affix">${esc(account.currency)}</span></div></div>
      <div class="field" style="margin-top:14px"><label for="cash-desc">Observação <span class="muted">(opcional)</span></label><input class="input" id="cash-desc" maxlength="140"></div>`,
    footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="cash-ok">${icon(isDeposit ? "deposit" : "withdraw")} ${isDeposit ? "Depositar" : "Levantar"}</button>`,
  });
  $("#cash-ok", s.el).addEventListener("click", async (ev) => {
    const input = $("#cash-amount", s.el);
    const amount = Number(input.value.replace(",", "."));
    if (!(amount > 0) || Math.round(amount * 100) !== amount * 100) return fieldError(input, "Montante inválido");
    busy(ev.currentTarget, true);
    try {
      const r = await api(`/accounts/${encodeURIComponent(account.iban)}/${kind}`, { method: "POST",
        body: { amount: amount.toFixed(2), description: $("#cash-desc", s.el).value || undefined } });
      toast(`${isDeposit ? "Depósito" : "Levantamento"} registado · novo saldo ${money(r.balance, r.currency)}`);
      s.close();
      onDone?.();
    } catch (ex) {
      busy(ev.currentTarget, false);
      fieldError(input, ex.status === 409 ? ex.message.replace("saldo insuficiente", "Saldo insuficiente") : ex.message);
    }
  });
}

async function detail(root, accountIban, claims, navigate) {
  const acc = await api(`/accounts/${encodeURIComponent(accountIban)}`);
  const ms = await movements(acc.iban, 300);
  const staff = claims.role !== "cliente";
  const region = REGIONS[acc.region];

  root.innerHTML = `
    <a class="btn btn-ghost" href="#/${staff ? "ops/accounts" : "accounts"}" style="margin-bottom:10px">${icon("chevronLeft")} ${staff ? "Contas de clientes" : "Contas"}</a>
    <div class="grid g-main">
      <section class="card card-pad balance-hero">
        <div class="row between"><span class="label">Conta à ordem · ${esc(acc.currency)}</span>
          <span class="chip" style="background:rgba(255,255,255,.14);color:#fff">${acc.status === "ATIVA" ? "Ativa" : "Bloqueada"}</span></div>
        <div class="big num">${esc(masked(money(acc.balance, acc.currency)))}</div>
        <div class="meta mono">${esc(iban(acc.iban))}</div>
        <div class="row wrap" style="margin-top:24px">
          ${staff ? (claims.role === "operador" ? `<button class="btn btn-white" id="dep">${icon("deposit")} Depósito</button><button class="btn btn-light" id="wd">${icon("withdraw")} Levantamento</button>` : "")
            : `<a class="btn btn-white" href="#/transfer?from=${encodeURIComponent(acc.iban)}">${icon("arrowUp")} Transferir</a>`}
          <button class="btn btn-light" data-copy="${esc(acc.iban)}" data-copy-label="IBAN copiado">${icon("copy")} Copiar IBAN</button>
        </div>
      </section>
      <section class="card card-pad">
        <h3>Dados da conta</h3>
        <dl class="kv" style="margin-top:8px">
          <dt>IBAN</dt><dd class="mono">${esc(iban(acc.iban))}</dd>
          <dt>Moeda</dt><dd>${esc(acc.currency)}</dd>
          <dt>Região / centro de dados</dt><dd>${esc(region?.name)} · ${esc(region?.city)}</dd>
          <dt>Limite diário</dt><dd class="num">${esc(money(acc.daily_limit, acc.currency))}</dd>
          <dt>Aberta em</dt><dd>${esc(date(acc.created_at))}</dd>
          ${staff ? `<dt>Titular (id)</dt><dd class="mono">${esc(acc.user_id.slice(0, 8))}…</dd>` : ""}
        </dl>
      </section>
    </div>
    <section class="card" style="margin-top:20px">
      <div class="card-head"><h3>Evolução do saldo</h3></div>
      <div id="chart"></div>
    </section>
    <section class="card" style="margin-top:20px">
      <div class="card-head"><h3>Extrato</h3><button class="btn btn-secondary btn-sm" id="csv">${icon("download")} CSV</button></div>
      <div class="table-wrap" style="margin-top:10px"><table class="table">
        <thead><tr><th>Data</th><th>Operação</th><th class="hide-sm">Referência</th><th class="r">Montante</th><th class="r hide-sm">Saldo</th></tr></thead>
        <tbody>${ms.length ? ms.map((m) => `
          <tr class="clickable" data-tx="${esc(m.tx_id)}">
            <td class="num" style="white-space:nowrap">${esc(dateTime(m.created_at))}</td>
            <td>${esc(originLabel(m.origin, m.type))}</td>
            <td class="mono muted hide-sm">${esc(m.tx_id.slice(0, 8))}</td>
            <td class="r"><span class="amount num ${m.type === "CREDITO" ? "amount-in" : ""}">${esc(masked(money(m.type === "CREDITO" ? m.amount : -m.amount, m.currency, { sign: true })))}</span></td>
            <td class="r num hide-sm">${esc(masked(money(m.balance_after, m.currency)))}</td>
          </tr>`).join("") : `<tr><td colspan="5"><div class="empty">Sem movimentos.</div></td></tr>`}</tbody></table></div>
    </section>`;

  areaChart($("#chart", root), balanceSeries(ms, acc.balance), acc.currency);
  bindCopy(root);
  root.querySelectorAll("[data-tx]").forEach((tr) => tr.addEventListener("click", () => {
    if (ms.find((m) => m.tx_id === tr.dataset.tx)?.origin === "TRANSFERENCIA" || !staff) navigate(`/tx/${encodeURIComponent(tr.dataset.tx)}`);
  }));
  const reload = () => detail(root, accountIban, claims, navigate);
  $("#dep", root)?.addEventListener("click", () => cashSheet(acc, "deposit", reload));
  $("#wd", root)?.addEventListener("click", () => cashSheet(acc, "withdraw", reload));
  $("#csv", root).addEventListener("click", () => {
    const csv = [["data", "operacao", "referencia", "montante", "moeda", "saldo"],
      ...ms.map((m) => [m.created_at, originLabel(m.origin, m.type), m.tx_id, (m.type === "CREDITO" ? 1 : -1) * m.amount, m.currency, m.balance_after])]
      .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `extrato-${acc.iban}.csv`;
    a.click();
  });
}
