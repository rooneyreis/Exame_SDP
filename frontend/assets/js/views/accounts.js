// Contas: lista (indicadores + cartões + dados para receber) e detalhe (cabeçalho com saldo e
// indicadores, dados da conta, gráfico, extrato paginado com filtros).
import { api } from "../api.js";
import { areaChart } from "../chart.js";
import { balanceSeries, convert, fxRates, movements } from "../data.js";
import { CURRENCY_NAMES, date, dateTime, iban, money, originLabel, REGION_CODES, REGIONS, regionName } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, bindCopy, bindPager, busy, confirmSheet, drawer, esc, fieldError, pagerHtml, paginate, sheet, toast } from "../ui.js";
import { masked, pageHead } from "./common.js";

const PAGE = 25;

export async function render({ root, params, claims, navigate }) {
  if (!params.iban) return list(root, claims);
  return detail(root, params.iban, claims, navigate);
}

const STATUS_LABEL = { ATIVA: "Ativa", BLOQUEADA: "Bloqueada", ENCERRADA: "Encerrada" };
const STATUS_CLASS = { ATIVA: "status-done", BLOQUEADA: "status-failed", ENCERRADA: "" };
const REQ_STATUS = { PENDENTE: ["status-pending", "clock", "Aguarda o operador"], APROVADO: ["status-done", "check", "Aprovado"], REJEITADO: ["status-failed", "x", "Rejeitado"] };
const CURRENCIES = ["EUR", "USD", "MZN"];

async function list(root, claims) {
  const [me, rates, limits, requests] = await Promise.all([
    api("/me"), fxRates(), api("/me/limits").catch(() => null), api("/account-requests").catch(() => []),
  ]);
  const accounts = me.accounts;
  const open = accounts.filter((a) => a.status !== "ENCERRADA");
  const home = REGIONS[claims.region]?.currency || "EUR";
  const total = open.reduce((s, a) => s + (convert(a.balance, a.currency, home, rates) ?? 0), 0);
  const pending = requests.filter((r) => r.status === "PENDENTE");
  const max = limits?.max_accounts ?? 5;
  const slots = max - open.length - pending.filter((r) => r.kind === "ABERTURA").length;
  const closing = new Set(pending.filter((r) => r.kind === "ENCERRAMENTO").map((r) => r.iban));

  root.innerHTML = `
    ${pageHead("Contas", "As suas contas em todas as regiões e moedas.",
      `<a class="btn btn-secondary" href="#/transfer">${icon("transfer")} Transferir</a>
       <button class="btn btn-primary" id="new-account" ${slots > 0 ? "" : "disabled title=\"Atingiu o máximo de contas\""}>${icon("plus")} Abrir nova conta</button>`)}
    ${me.unavailable_regions?.length ? `<div class="banner banner-warn" style="margin-bottom:var(--gap)">${icon("alert")}<span>A região ${me.unavailable_regions.map((r) => esc(regionName(r))).join(", ")} está temporariamente indisponível: as contas dessa região não aparecem até o serviço voltar. As restantes funcionam normalmente.</span></div>` : ""}
    <section class="panel"><div class="metric-strip" style="--n:4">
      <div class="metric"><span class="m-label">${icon("wallet")} Património total</span><span class="m-value">${esc(masked(money(total, home)))}</span><span class="m-sub">convertido para ${esc(home)} ao câmbio do dia</span></div>
      <div class="metric"><span class="m-label">${icon("bank")} Contas ativas</span><span class="m-value">${open.length}<span class="soft" style="font-size:1rem"> / ${max}</span></span><span class="m-sub">${slots > 0 ? `pode abrir mais ${slots}` : "máximo atingido"}</span></div>
      <div class="metric"><span class="m-label">${icon("globe")} Regiões</span><span class="m-value" style="font-size:1.3rem">${[...new Set(open.map((a) => a.region))].map((r) => esc(REGIONS[r]?.city || r)).join(" · ") || "—"}</span><span class="m-sub">cada conta fica no centro de dados da sua região</span></div>
      <div class="metric"><span class="m-label">${icon("clock")} Pedidos pendentes</span><span class="m-value">${pending.length}</span><span class="m-sub">aguardam um operador</span></div>
    </div></section>
    <div class="bento mt">
      <div class="c-8"><div class="tile-grid">${accounts.map((a) => {
        const conv = a.currency !== home ? convert(a.balance, a.currency, home, rates) : null;
        return `
        <a class="tile ${a.status === "ENCERRADA" ? "closed" : ""}" href="#/accounts/${encodeURIComponent(a.iban)}" ${a.status === "ENCERRADA" ? 'style="opacity:.62"' : ""}>
          <div class="tile-top"><span class="region-tag">${esc(a.region)}</span><span class="grow"><span class="name">${esc(regionName(a.region))} · ${esc(REGIONS[a.region]?.city || "")}</span><span class="meta" style="display:block">Conta à ordem em ${esc(CURRENCY_NAMES[a.currency] || a.currency)}</span></span>
            <span class="chip ${STATUS_CLASS[a.status] ?? ""}">${esc(STATUS_LABEL[a.status] || a.status)}</span></div>
          <div><div class="metric" style="padding:0"><span class="m-value">${esc(masked(money(a.balance, a.currency)))}</span></div>
            <div class="meta num" style="margin-top:2px">${conv != null ? `≈ ${esc(masked(money(conv, home)))}` : "&nbsp;"}</div>
            <div class="mono meta" style="margin-top:6px">${esc(iban(a.iban))}</div></div>
          <div class="meta">${closing.has(a.iban) ? `${icon("clock")} Encerramento pedido` : a.status === "ENCERRADA" ? `Encerrada em ${esc(date(a.closed_at))}` : `Limite da conta ${esc(money(a.daily_limit, a.currency))}/dia`}</div>
        </a>`; }).join("")}
        ${slots > 0 ? `<button class="tile add" id="new-account-tile">${icon("plus")}<span>Abrir nova conta</span><span class="meta">Europa, América ou África · EUR, USD ou MZN</span></button>` : ""}</div></div>
      <aside class="c-4 stack-gap">
        <section class="panel"><div class="panel-head"><div><h3>Pedidos de contas</h3><div class="sub">abertura e encerramento</div></div></div>
          <div>${requests.slice(0, 6).map((r) => {
            const [cls, ic, label] = REQ_STATUS[r.status] || ["", "clock", r.status];
            return `<div class="queue-item">
              <span class="tx-icon">${icon(r.kind === "ABERTURA" ? "plus" : "x")}</span>
              <span class="q-main"><b>${r.kind === "ABERTURA" ? "Abertura" : "Encerramento"} · ${esc(r.region)} · ${esc(r.currency)}</b>
                <span>${r.iban ? `${esc(iban(r.iban))} · ` : ""}${esc(dateTime(r.created_at))}${r.status === "REJEITADO" && r.decision_reason ? ` · motivo: ${esc(r.decision_reason)}` : ""}</span></span>
              <span class="chip ${cls}">${icon(ic)}${esc(label)}</span></div>`; }).join("") ||
            `<div class="empty-sm">Ainda não fez pedidos. Use "Abrir nova conta" para ter uma conta noutra região ou moeda.</div>`}</div>
        </section>
        <section class="panel"><div class="panel-head"><div><h3>Dados para receber</h3><div class="sub">partilhe o IBAN para receber transferências</div></div></div>
          <div class="rows">${open.map((a) => `<div class="r-item" style="cursor:default"><span class="cur-badge">${esc(a.currency)}</span>
            <span style="min-width:0"><span class="r-title mono">${esc(iban(a.iban))}</span><span class="r-sub">${esc(regionName(a.region))} · ${esc(REGIONS[a.region]?.city || "")}</span></span>
            <button class="btn btn-ghost btn-icon" data-copy="${esc(a.iban)}" data-copy-label="IBAN copiado" aria-label="Copiar IBAN">${icon("copy")}</button></div>`).join("")}</div>
        </section>
      </aside>
    </div>`;
  bindCopy(root);
  const openSheet = () => openAccountSheet({ open, pending, slots, onDone: () => list(root, claims) });
  $("#new-account", root)?.addEventListener("click", openSheet);
  $("#new-account-tile", root)?.addEventListener("click", openSheet);
}

/** Pedido de conta adicional: escolher região e moeda (combinações já existentes desativadas). */
function openAccountSheet({ open, pending, slots, onDone }) {
  const taken = new Set([...open.map((a) => `${a.region}:${a.currency}`),
    ...pending.filter((r) => r.kind === "ABERTURA").map((r) => `${r.region}:${r.currency}`)]);
  const sel = { region: null, currency: null };
  const s = drawer({
    title: "Abrir nova conta",
    subtitle: `Pode ter mais ${slots} conta(s). O pedido é aprovado por um operador.`,
    body: `
      <div class="field"><span class="label">Região (onde ficam os dados)</span>
        <div class="region-choices" role="radiogroup" aria-label="Região">${REGION_CODES.map((r) => `
          <button type="button" class="choice region-choice" role="radio" aria-checked="false" data-r="${r}">
            <span class="region-tag">${r}</span><span class="grow"><b>${esc(REGIONS[r].name)}</b><span>${esc(REGIONS[r].city)} · contas GS-${r}</span></span></button>`).join("")}</div></div>
      <div class="field" style="margin-top:18px"><span class="label">Moeda da conta</span>
        <div class="segmented" role="group" aria-label="Moeda" id="cur-group">${CURRENCIES.map((c) => `<button type="button" data-c="${c}" aria-pressed="false">${c}</button>`).join("")}</div>
        <p class="hint" id="cur-hint">Escolha primeiro a região.</p></div>
      <div class="banner banner-info" style="margin-top:18px">${icon("info")}<span>Depois de aprovada, a conta aparece aqui com o seu IBAN. Transferências entre as suas contas não contam para o limite diário.</span></div>
      <div id="acc-err" style="margin-top:12px"></div>`,
    footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="acc-ok" disabled>${icon("check")} Pedir abertura</button>`,
  });
  const el = s.el;
  function refresh() {
    $$("[data-r]", el).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.r === sel.region)));
    $$("[data-c]", el).forEach((b) => {
      const used = !sel.region || taken.has(`${sel.region}:${b.dataset.c}`);
      b.disabled = used;
      if (used && sel.currency === b.dataset.c) sel.currency = null;
      b.setAttribute("aria-pressed", String(b.dataset.c === sel.currency));
    });
    $("#cur-hint", el).textContent = !sel.region ? "Escolha primeiro a região."
      : CURRENCIES.every((c) => taken.has(`${sel.region}:${c}`)) ? "Já tem (ou pediu) contas em todas as moedas desta região."
      : `A moeda base em ${REGIONS[sel.region].city} é ${REGIONS[sel.region].currency}; pode escolher outra. As já existentes estão desativadas.`;
    $("#acc-ok", el).disabled = !(sel.region && sel.currency);
  }
  $$("[data-r]", el).forEach((b) => b.addEventListener("click", () => {
    sel.region = b.dataset.r;
    if (!sel.currency && !taken.has(`${sel.region}:${REGIONS[sel.region].currency}`)) sel.currency = REGIONS[sel.region].currency;
    refresh();
  }));
  $$("[data-c]", el).forEach((b) => b.addEventListener("click", () => { sel.currency = b.dataset.c; refresh(); }));
  $("#acc-ok", el).addEventListener("click", async (e) => {
    busy(e.currentTarget, true, "A enviar…");
    try {
      await api("/account-requests", { method: "POST", body: { region: sel.region, currency: sel.currency } });
      s.close();
      toast(`Pedido de conta ${sel.currency} em ${REGIONS[sel.region].city} enviado`);
      onDone();
    } catch (ex) {
      busy(e.currentTarget, false);
      $("#acc-err", el).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
    }
  });
  refresh();
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
          <div class="h-label">${icon("wallet")} Conta à ordem · ${esc(acc.currency)} · ${esc(STATUS_LABEL[acc.status] || acc.status)}</div>
          <div class="h-value">${esc(masked(money(acc.balance, acc.currency)))}</div>
          <div class="h-meta mono">${esc(iban(acc.iban))}</div>
        </div>
        <div class="h-actions">
          ${staff ? (claims.role === "operador" ? `<button class="btn btn-white" id="dep">${icon("deposit")} Depósito</button><button class="btn btn-light" id="wd">${icon("withdraw")} Levantamento</button>` : "")
            : acc.status === "ATIVA" ? `<a class="btn btn-white" href="#/transfer?from=${encodeURIComponent(acc.iban)}">${icon("arrowUp")} Transferir</a>` : ""}
          ${!staff && acc.status !== "ENCERRADA" ? `<button class="btn btn-light" id="close-acc">${icon("x")} Pedir encerramento</button>` : ""}
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
          ${acc.closed_at ? `<dt>Encerrada em</dt><dd>${esc(date(acc.closed_at))}</dd>` : ""}
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
  $("#close-acc", root)?.addEventListener("click", () => closeAccount(acc, reload));
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


/** Pedido de encerramento (cliente). Só com saldo 0: o operador confirma depois. */
async function closeAccount(acc, onDone) {
  if (Number(acc.balance) !== 0) {
    const s = sheet({
      title: "Encerrar conta",
      body: `<p>Para encerrar a conta <span class="mono">${esc(iban(acc.iban))}</span>, o saldo tem de ser <b>0</b>.</p>
        <p class="soft" style="margin-top:10px">Saldo atual: <b class="num">${esc(money(acc.balance, acc.currency))}</b>. Transfira-o primeiro para outra conta (pode ser uma das suas) e volte a pedir o encerramento.</p>`,
      footer: `<button class="btn btn-secondary" data-close>Fechar</button><a class="btn btn-primary" href="#/transfer?from=${encodeURIComponent(acc.iban)}&own=1">${icon("transfer")} Transferir o saldo</a>`,
    });
    $("a.btn-primary", s.el).addEventListener("click", () => s.close());
    return;
  }
  if (!await confirmSheet({ title: "Encerrar conta", message: `Pedir o encerramento da conta ${esc(iban(acc.iban))}? Um operador confirma o pedido; a conta fica registada como encerrada e deixa de receber e enviar dinheiro.`, confirm: "Pedir encerramento", danger: true })) return;
  try {
    await api(`/accounts/${encodeURIComponent(acc.iban)}/closure`, { method: "POST" });
    toast("Pedido de encerramento enviado ao operador");
    onDone();
  } catch (ex) {
    toast(ex.message, "bad");
  }
}
