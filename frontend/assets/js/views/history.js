import { activity, myAccounts } from "../data.js";
import { dateTime, iban, kindLabel, money } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, esc, statusChip } from "../ui.js";
import { activityRow, amountHtml, pageHead, txIcon } from "./common.js";

export async function render({ root, query, navigate }) {
  const accounts = await myAccounts();
  const items = await activity(accounts, { limit: 300 });
  const f = { account: query.get("account") || "all", type: "all", status: "all", q: "" };

  root.innerHTML = `
    ${pageHead("Movimentos", "Todas as operações das suas contas, incluindo transferências enviadas a partir deste dispositivo que não chegaram a ser realizadas.",
      `<button class="btn btn-secondary" id="csv">${icon("download")} Exportar CSV</button><a class="btn btn-primary" href="#/transfer">${icon("transfer")} Transferir</a>`)}
    <div class="card">
      <div class="toolbar">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Pesquisar por nome, IBAN ou referência" aria-label="Pesquisar"></div>
        <select class="select" id="f-account" aria-label="Conta" style="width:auto">
          <option value="all">Todas as contas</option>
          ${accounts.map((a) => `<option value="${esc(a.iban)}" ${f.account === a.iban ? "selected" : ""}>${esc(a.currency)} · ${esc(a.iban.slice(-4))}</option>`).join("")}
        </select>
        <select class="select" id="f-type" aria-label="Tipo" style="width:auto">
          <option value="all">Todos os tipos</option><option value="out">Enviadas</option><option value="in">Recebidas</option>
          <option value="intl">Internacionais</option><option value="cash">Depósitos e levantamentos</option>
        </select>
        <div class="segmented" role="group" aria-label="Estado">
          ${[["all", "Todos"], ["done", "Processadas"], ["pending", "Pendentes"], ["failed", "Falhadas"]].map(([k, l]) => `<button data-status="${k}" aria-pressed="${k === "all"}">${l}</button>`).join("")}
        </div>
      </div>
      <div class="table-wrap hide-sm"><table class="table">
        <thead><tr><th>Data</th><th>Descrição</th><th>Conta</th><th>Tipo</th><th>Estado</th><th class="r">Montante</th></tr></thead>
        <tbody id="rows"></tbody></table></div>
      <ul class="list show-sm" id="list"></ul>
      <div id="empty"></div>
      <div class="row between" style="padding:14px 24px;border-top:1px solid var(--line)"><span class="hint" id="count"></span></div>
    </div>`;

  function filtered() {
    const q = f.q.toLowerCase();
    return items.filter((i) =>
      (f.account === "all" || i.account === f.account) &&
      (f.status === "all" || i.status.key === f.status) &&
      (f.type === "all" || (f.type === "in" && i.direction === "in" && i.origin === "TRANSFERENCIA") ||
        (f.type === "out" && i.direction === "out" && i.origin === "TRANSFERENCIA") ||
        (f.type === "intl" && i.kind === "DISTRIBUIDA") || (f.type === "cash" && i.origin !== "TRANSFERENCIA")) &&
      (!q || [i.title, i.counterparty, i.txId, i.category].some((v) => (v || "").toLowerCase().includes(q))));
  }

  function draw() {
    const list = filtered();
    $("#rows", root).innerHTML = list.map((i) => `
      <tr class="clickable" data-tx="${esc(i.txId)}" tabindex="0">
        <td class="num" style="white-space:nowrap">${esc(dateTime(i.date))}</td>
        <td><div class="row">${txIcon(i)}<div style="min-width:0"><b style="font-weight:560">${esc(i.title)}</b><div class="hint">${esc(i.category)}${i.counterparty && !i.title.includes(iban(i.counterparty)) ? ` · ${esc(iban(i.counterparty))}` : ""}</div></div></div></td>
        <td class="mono muted">${esc(i.account.slice(-4))}</td>
        <td>${i.kind ? `<span class="chip ${i.kind === "DISTRIBUIDA" ? "chip-accent" : ""}">${esc(kindLabel(i.kind))}</span>` : "—"}</td>
        <td>${statusChip(i.status)}</td>
        <td class="r">${amountHtml(i)}</td>
      </tr>`).join("");
    $("#list", root).innerHTML = list.map((i) => `<li>${activityRow(i)}</li>`).join("");
    $("#empty", root).innerHTML = list.length ? "" : `<div class="empty"><div class="tx-icon">${icon("search")}</div><h3>Sem resultados</h3><p>Ajuste os filtros ou a pesquisa.</p></div>`;
    $("#count", root).textContent = `${list.length} de ${items.length} movimentos`;
    $$("[data-tx]", root).forEach((tr) => {
      const go = () => navigate(`/tx/${encodeURIComponent(tr.dataset.tx)}`);
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
  }

  $("#q", root).addEventListener("input", (e) => { f.q = e.target.value; draw(); });
  $("#f-account", root).addEventListener("change", (e) => { f.account = e.target.value; draw(); });
  $("#f-type", root).addEventListener("change", (e) => { f.type = e.target.value; draw(); });
  $$("[data-status]", root).forEach((b) => b.addEventListener("click", () => {
    f.status = b.dataset.status;
    $$("[data-status]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    draw();
  }));
  $("#csv", root).addEventListener("click", () => {
    const rows = [["data", "descricao", "categoria", "conta", "contraparte", "tipo", "estado", "montante", "moeda", "referencia"],
      ...filtered().map((i) => [i.date, i.title, i.category, i.account, i.counterparty || "", i.kind ? kindLabel(i.kind) : "",
        i.status.label, (i.direction === "in" ? 1 : -1) * i.amount, i.currency, i.txId])];
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `movimentos-global-scale-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
  draw();
  void money;
}
