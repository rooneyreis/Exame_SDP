// Contas: lista (indicadores + cartões + dados para receber) e detalhe (cabeçalho com saldo e
// indicadores, dados da conta, gráfico, extrato paginado com filtros).
import { api } from "../api.js";
import { areaChart } from "../chart.js";
import { balanceSeries, convert, fxRates, movements, myAccounts } from "../data.js";
import { date, dateTime, iban, money, originLabel, REGIONS, regionName } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, bindCopy, bindPager, busy, esc, fieldError, pagerHtml, paginate, sheet, toast } from "../ui.js";
import { masked, pageHead } from "./common.js";

const PAGE = 25;

export async function render({ root, params, claims, navigate }) {
  if (!params.iban) return list(root, claims);
  return detail(root, params.iban, claims, navigate);
}

async function list(root, claims) {
  const [accounts, rates] = await Promise.all([myAccounts(), fxRates()]);
  const home = claims.region === "AM" ? "USD" : "EUR";
  const total = accounts.reduce((s, a) => s + (convert(a.balance, a.currency, home, rates) ?? 0), 0);
  const recent = await Promise.all(accounts.map((a) => movements(a.iban, 100).catch(() => [])));
  root.innerHTML = `
    ${pageHead("Contas", "As suas contas à ordem e respetivos dados bancários.", `<a class="btn btn-primary" href="#/transfer">${icon("transfer")} Transferir</a>`)}
    <section class="panel"><div class="metric-strip" style="--n:4">
      <div class="metric"><span class="m-label">${icon("wallet")} Saldo total estimado</span><span class="m-value">${esc(masked(money(total, home)))}</span><span class="m-sub">em ${esc(home)} ao câmbio do dia</span></div>
      <div class="metric"><span class="m-label">${icon("bank")} Contas</span><span class="m-value">${accounts.length}</span><span class="m-sub">${accounts.filter((a) => a.status === "ATIVA").length} ativa(s)</span></div>
      <div class="metric"><span class="m-label">${icon("globe")} Centro de dados</span><span class="m-value" style="font-size:1.3rem">${esc(REGIONS[claims.region]?.city || "—")}</span><span class="m-sub">${esc(REGIONS[claims.region]?.name || "")} · os seus dados ficam na sua região</span></div>
      <div class="metric"><span class="m-label">${icon("history")} Movimentos registados</span><span class="m-value">${recent.reduce((s, r) => s + r.length, 0)}</span><span class="m-sub">nas suas contas</span></div>
    </div></section>
    <div class="bento mt">
      <div class="c-8"><div class="tile-grid">${accounts.map((a, i) => `
        <a class="tile" href="#/accounts/${encodeURIComponent(a.iban)}">
          <div class="tile-top"><span class="cur-badge">${esc(a.currency)}</span><span class="grow"><span class="name">Conta à ordem</span><span class="meta" style="display:block">${regionName(a.region)}</span></span>
            <span class="chip ${a.status === "ATIVA" ? "status-done" : "status-failed"}">${a.status === "ATIVA" ? "Ativa" : "Bloqueada"}</span></div>
          <div><div class="metric" style="padding:0"><span class="m-value">${esc(masked(money(a.balance, a.currency)))}</span></div>
            <div class="mono meta" style="margin-top:6px">${esc(iban(a.iban))}</div></div>
          <div class="meta">${recent[i].length} movimento(s) · limite diário ${esc(money(a.daily_limit, a.currency))}</div>
        </a>`).join("")}</div></div>
      <aside class="c-4 stack-gap">
        <section class="panel"><div class="panel-head"><div><h3>Dados para receber</h3><div class="sub">partilhe o IBAN para receber transferências</div></div></div>
          <div class="rows">${accounts.map((a) => `<div class="r-item" style="cursor:default"><span class="cur-badge">${esc(a.currency)}</span>
            <span style="min-width:0"><span class="r-title mono">${esc(iban(a.iban))}</span><span class="r-sub">${regionName(a.region)} · ${REGIONS[a.region]?.city || ""}</span></span>
            <button class="btn btn-ghost btn-icon" data-copy="${esc(a.iban)}" data-copy-label="IBAN copiado" aria-label="Copiar IBAN">${icon("copy")}</button></div>`).join("")}</div>
        </section>
        <section class="panel"><div class="panel-body" style="padding-top:20px"><div class="row" style="align-items:flex-start;gap:14px">
          <span class="tx-icon">${icon("info")}</span>
          <div><h3>Precisa de outra moeda?</h3><p class="soft" style="margin-top:4px;font-size:.88rem">As contas em EUR, USD e MZN são abertas por um operador após verificação. Contacte o seu gestor de conta.</p></div>
        </div></div></section>
      </aside>
    </div>`;
  bindCopy(root);
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
  const since = Date.now() - 30 * 86400000;
  const last30 = ms.filter((m) => new Date(m.created_at).getTime() >= since);
  const sumType = (list, t) => list.filter((m) => m.type === t).reduce((s, m) => s + Number(m.amount), 0);
  const back = staff ? (claims.role === "operador" ? "/ops/accounts" : "/admin/accounts") : "/accounts";
  const f = { type: "all", q: "", page: 1 };

  root.innerHTML = `
    <a class="btn btn-ghost" href="#${back}" style="margin:-6px 0 10px -10px">${icon("chevronLeft")} ${staff ? "Contas de clientes" : "Contas"}</a>
    <div class="bento">
      <section class="hero c-8">
        <div>
          <div class="h-label">${icon("wallet")} Conta à ordem · ${esc(acc.currency)} · ${acc.status === "ATIVA" ? "Ativa" : "Bloqueada"}</div>
          <div class="h-value">${esc(masked(money(acc.balance, acc.currency)))}</div>
          <div class="h-meta mono">${esc(iban(acc.iban))}</div>
        </div>
        <div class="h-actions">
          ${staff ? (claims.role === "operador" ? `<button class="btn btn-white" id="dep">${icon("deposit")} Depósito</button><button class="btn btn-light" id="wd">${icon("withdraw")} Levantamento</button>` : "")
            : `<a class="btn btn-white" href="#/transfer?from=${encodeURIComponent(acc.iban)}">${icon("arrowUp")} Transferir</a>`}
          <button class="btn btn-light" data-copy="${esc(acc.iban)}" data-copy-label="IBAN copiado">${icon("copy")} Copiar IBAN</button>
        </div>
        <div class="h-stats">
          <div><span>Entradas · 30 dias</span><b>${esc(masked(money(sumType(last30, "CREDITO"), acc.currency)))}</b></div>
          <div><span>Saídas · 30 dias</span><b>${esc(masked(money(sumType(last30, "DEBITO"), acc.currency)))}</b></div>
          <div><span>Movimentos · 30 dias</span><b>${last30.length}</b></div>
          <div><span>Limite diário</span><b>${esc(money(acc.daily_limit, acc.currency))}</b></div>
        </div>
      </section>
      <section class="panel c-4">
        <div class="panel-head"><h3>Dados da conta</h3></div>
        <div class="panel-body"><dl class="kv">
          <dt>IBAN</dt><dd class="mono">${esc(iban(acc.iban))}</dd>
          <dt>Moeda</dt><dd>${esc(acc.currency)}</dd>
          <dt>Região</dt><dd>${esc(region?.name)} · ${esc(region?.city)}</dd>
          <dt>Nó de dados</dt><dd class="mono">${REGIONS[acc.region]?.node || "—"}</dd>
          <dt>Aberta em</dt><dd>${esc(date(acc.created_at))}</dd>
          ${staff ? `<dt>Titular (id)</dt><dd class="mono">${esc(acc.user_id.slice(0, 8))}…</dd>` : ""}
        </dl></div>
      </section>
    </div>
    <section class="panel mt">
      <div class="panel-head"><div><h3>Evolução do saldo</h3><div class="sub">últimos ${ms.length} movimentos</div></div></div>
      <div class="panel-body flush" id="chart"></div>
    </section>
    <section class="panel mt">
      <div class="panel-head"><h3>Extrato</h3><div class="tools"><button class="btn btn-secondary btn-sm" id="csv">${icon("download")} CSV</button></div></div>
      <div class="filters" style="border-top:1px solid var(--line)">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Referência ou operação" aria-label="Pesquisar no extrato"></div>
        <span class="grow"></span>
        ${[["all", "Todos"], ["CREDITO", "Entradas"], ["DEBITO", "Saídas"]].map(([k, l]) => `<button class="chip-filter" data-type="${k}" aria-pressed="${k === "all"}">${l}</button>`).join("")}
      </div>
      <div id="statement"></div>
    </section>`;

  areaChart($("#chart", root), balanceSeries(ms, acc.balance), acc.currency, { height: 240 });
  bindCopy(root);

  const filtered = () => ms.filter((m) => (f.type === "all" || m.type === f.type) &&
    (!f.q || [m.tx_id, originLabel(m.origin, m.type), m.description].some((v) => (v || "").toLowerCase().includes(f.q))));
  function draw() {
    const list = filtered();
    const pg = paginate(list, f.page, PAGE);
    f.page = pg.page;
    $("#statement", root).innerHTML = list.length ? `<div class="table-wrap"><table class="table">
      <thead><tr><th class="w-date">Data</th><th>Operação</th><th class="hide-sm w-mono">Referência</th><th class="w-money">Montante</th><th class="w-money hide-sm">Saldo</th></tr></thead>
      <tbody>${pg.slice.map((m) => `
        <tr class="clickable" data-tx="${esc(m.tx_id)}" data-origin="${esc(m.origin)}" tabindex="0">
          <td class="w-date num">${esc(dateTime(m.created_at))}</td>
          <td><span class="cell-main">${esc(originLabel(m.origin, m.type))}</span>${m.description ? `<div class="cell-sub">${esc(m.description)}</div>` : ""}</td>
          <td class="mono muted hide-sm w-mono">${esc(m.tx_id.slice(0, 8))}</td>
          <td class="w-money"><span class="amount num ${m.type === "CREDITO" ? "amount-in" : ""}">${esc(masked(money(m.type === "CREDITO" ? m.amount : -m.amount, m.currency, { sign: true })))}</span></td>
          <td class="w-money num hide-sm">${esc(masked(money(m.balance_after, m.currency)))}</td>
        </tr>`).join("")}</tbody></table></div>${pagerHtml(pg, "movimentos")}`
      : `<div class="empty-sm">Sem movimentos.</div>`;
    $$("[data-tx]", root).forEach((tr) => {
      const go = () => { if (tr.dataset.origin === "TRANSFERENCIA" || !staff) navigate(`/tx/${encodeURIComponent(tr.dataset.tx)}`); };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
    bindPager($("#statement", root), (p) => { f.page = p; draw(); });
  }
  let t;
  $("#q", root).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim().toLowerCase(); f.page = 1; draw(); }, 200); });
  $$("[data-type]", root).forEach((b) => b.addEventListener("click", () => {
    f.type = b.dataset.type; f.page = 1;
    $$("[data-type]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    draw();
  }));
  draw();

  const reload = () => detail(root, accountIban, claims, navigate);
  $("#dep", root)?.addEventListener("click", () => cashSheet(acc, "deposit", reload));
  $("#wd", root)?.addEventListener("click", () => cashSheet(acc, "withdraw", reload));
  $("#csv", root).addEventListener("click", () => {
    const csv = [["data", "operacao", "referencia", "montante", "moeda", "saldo"],
      ...filtered().map((m) => [m.created_at, originLabel(m.origin, m.type), m.tx_id, (m.type === "CREDITO" ? 1 : -1) * m.amount, m.currency, m.balance_after])]
      .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `extrato-${acc.iban}.csv`;
    a.click();
  });
}
