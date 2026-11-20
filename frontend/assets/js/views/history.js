// Movimentos do cliente: resumo do filtro ativo, tabela paginada e detalhe em painel lateral.
import { activity, myAccounts } from "../data.js";
import { dateTime, iban, kindLabel, money, settlementLabel } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, bindPager, drawer, esc, pagerHtml, paginate, statusChip } from "../ui.js";
import { amountHtml, pageHead, txIcon } from "./common.js";
import { friendlyFailure } from "./transfer.js";

const PAGE = 25;

export async function render({ root, query, navigate }) {
  const accounts = await myAccounts();
  const items = await activity(accounts, { limit: 300 });
  const f = { account: query.get("account") || "all", type: "all", status: "all", q: "", page: 1 };

  root.innerHTML = `
    ${pageHead("Movimentos", "Todas as operações das suas contas.",
      `<button class="btn btn-secondary" id="csv">${icon("download")} Exportar CSV</button><a class="btn btn-primary" href="#/transfer">${icon("transfer")} Transferir</a>`)}
    <section class="panel" id="summary"></section>
    <section class="panel mt">
      <div class="filters">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Nome, IBAN ou referência" aria-label="Pesquisar"></div>
        <select class="select" id="f-account" aria-label="Conta"><option value="all">Todas as contas</option>
          ${accounts.map((a) => `<option value="${esc(a.iban)}" ${f.account === a.iban ? "selected" : ""}>${esc(a.currency)} · ${esc(a.iban.slice(-4))}</option>`).join("")}</select>
        <select class="select" id="f-type" aria-label="Tipo"><option value="all">Todos os tipos</option><option value="out">Enviadas</option><option value="in">Recebidas</option>
          <option value="intl">Internacionais</option><option value="cash">Depósitos e levantamentos</option></select>
        <span class="grow"></span>
        ${[["all", "Todos"], ["done", "Processadas"], ["pending", "Pendentes"], ["failed", "Falhadas"]].map(([k, l]) => `<button class="chip-filter" data-status="${k}" aria-pressed="${k === "all"}">${l}</button>`).join("")}
      </div>
      <div id="table"></div>
    </section>`;

  function filtered() {
    const q = f.q.toLowerCase();
    return items.filter((i) =>
      (f.account === "all" || i.account === f.account) && (f.status === "all" || i.status.key === f.status) &&
      (f.type === "all" || (f.type === "in" && i.direction === "in" && i.origin === "TRANSFERENCIA") ||
        (f.type === "out" && i.direction === "out" && i.origin === "TRANSFERENCIA") ||
        (f.type === "intl" && i.kind === "DISTRIBUIDA") || (f.type === "cash" && i.origin !== "TRANSFERENCIA")) &&
      (!q || [i.title, i.counterparty, i.txId, i.category].some((v) => (v || "").toLowerCase().includes(q))));
  }

  function summary(list) {
    const byCur = (dir) => {
      const m = {};
      list.filter((i) => i.direction === dir && i.status.key !== "failed").forEach((i) => { m[i.currency] = (m[i.currency] || 0) + i.amount; });
      return Object.entries(m).map(([c, v]) => money(v, c)).join(" · ") || "—";
    };
    $("#summary", root).innerHTML = `<div class="metric-strip" style="--n:4">
      <div class="metric"><span class="m-label">${icon("history")} Movimentos</span><span class="m-value">${list.length}</span><span class="m-sub">no filtro atual</span></div>
      <div class="metric"><span class="m-label">${icon("arrowDown")} Entradas</span><span class="m-value amount-in" style="font-size:1.3rem">${esc(byCur("in"))}</span></div>
      <div class="metric"><span class="m-label">${icon("arrowUp")} Saídas</span><span class="m-value" style="font-size:1.3rem">${esc(byCur("out"))}</span></div>
      <div class="metric"><span class="m-label">${icon("alert")} Falhadas / pendentes</span><span class="m-value">${list.filter((i) => i.status.key === "failed").length} / ${list.filter((i) => i.status.key === "pending").length}</span></div>
    </div>`;
  }

  function draw() {
    const list = filtered();
    summary(list);
    const pg = paginate(list, f.page, PAGE);
    f.page = pg.page;
    $("#table", root).innerHTML = list.length ? `<div class="table-wrap"><table class="table">
      <thead><tr><th class="w-date">Data</th><th>Descrição</th><th class="hide-sm">Conta</th><th class="hide-sm">Tipo</th><th class="w-status">Estado</th><th class="w-money">Montante</th></tr></thead>
      <tbody>${pg.slice.map((i, k) => `
        <tr class="clickable" data-k="${k}" tabindex="0">
          <td class="w-date num">${esc(dateTime(i.date))}</td>
          <td><div class="row" style="gap:12px">${txIcon(i)}<div style="min-width:0"><div class="cell-main">${esc(i.title)}</div><div class="cell-sub">${esc(i.category)}</div></div></div></td>
          <td class="hide-sm mono muted">•••• ${esc(i.account.slice(-4))}</td>
          <td class="hide-sm">${i.kind ? `<span class="chip ${i.kind === "DISTRIBUIDA" ? "chip-accent" : ""}">${esc(kindLabel(i.kind))}</span>` : "—"}</td>
          <td class="w-status">${statusChip(i.status)}</td>
          <td class="w-money">${amountHtml(i)}</td>
        </tr>`).join("")}</tbody></table></div>${pagerHtml(pg, "movimentos")}`
      : `<div class="empty"><div class="tx-icon">${icon("search")}</div><h3>Sem resultados</h3><p>Ajuste os filtros ou a pesquisa.</p></div>`;
    $$("[data-k]", root).forEach((tr) => {
      const open = () => detail(pg.slice[+tr.dataset.k]);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
    bindPager(root, (p) => { f.page = p; draw(); });
  }

  function detail(i) {
    const t = i.transfer;
    drawer({
      title: i.title, subtitle: `${esc(i.category)} · ${esc(dateTime(i.date))}`,
      body: `
        <div class="detail-hero">${txIcon(i)}<div><div class="big">${amountHtml(i)}</div><div style="margin-top:6px">${statusChip(i.status)}</div></div></div>
        ${i.status.key === "failed" ? `<div class="banner banner-bad" style="margin-bottom:12px">${icon("alert")}<span>${esc(friendlyFailure(i.failureReason || t?.failure_reason))}</span></div>` : ""}
        <dl class="kv">
          <dt>Conta</dt><dd class="mono">${esc(iban(i.account))}</dd>
          ${i.counterparty ? `<dt>${i.direction === "out" ? "Destino" : "Origem"}</dt><dd class="mono">${esc(iban(i.counterparty))}</dd>` : ""}
          ${i.kind ? `<dt>Tipo</dt><dd>${esc(kindLabel(i.kind))}</dd>` : ""}
          ${t && t.from_currency !== t.to_currency ? `<dt>Câmbio</dt><dd class="num">1 ${esc(t.from_currency)} = ${esc(Number(t.fx_rate).toFixed(4))} ${esc(t.to_currency)}</dd><dt>Creditado</dt><dd class="num">${esc(money(t.converted_amount, t.to_currency))}</dd>` : ""}
          ${i.balanceAfter != null && !Number.isNaN(i.balanceAfter) ? `<dt>Saldo após</dt><dd class="num">${esc(money(i.balanceAfter, i.currency))}</dd>` : ""}
          ${t?.kind === "DISTRIBUIDA" ? `<dt>Liquidação</dt><dd>${esc(settlementLabel(t.settlement_status))}</dd>` : ""}
          <dt>Referência</dt><dd class="mono" style="font-size:.78rem">${esc(i.txId)}</dd>
        </dl>`,
      footer: `<button class="btn btn-secondary" data-close>Fechar</button><a class="btn btn-primary" href="#/tx/${encodeURIComponent(i.txId)}">${icon("doc")} Comprovativo</a>`,
    });
  }

  let timer;
  $("#q", root).addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { f.q = e.target.value; f.page = 1; draw(); }, 200); });
  $("#f-account", root).addEventListener("change", (e) => { f.account = e.target.value; f.page = 1; draw(); });
  $("#f-type", root).addEventListener("change", (e) => { f.type = e.target.value; f.page = 1; draw(); });
  $$("[data-status]", root).forEach((b) => b.addEventListener("click", () => {
    f.status = b.dataset.status; f.page = 1;
    $$("[data-status]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    draw();
  }));
  $("#csv", root).addEventListener("click", () => {
    const rows = [["data", "descricao", "categoria", "conta", "contraparte", "tipo", "estado", "montante", "moeda", "referencia"],
      ...filtered().map((i) => [i.date, i.title, i.category, i.account, i.counterparty || "", i.kind ? kindLabel(i.kind) : "", i.status.label, (i.direction === "in" ? 1 : -1) * i.amount, i.currency, i.txId])];
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `movimentos-global-scale-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  });
  draw();
  void navigate;
}
