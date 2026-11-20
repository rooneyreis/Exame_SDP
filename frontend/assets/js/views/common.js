// Peças partilhadas entre páginas.
import { iban, ibanShort, kindLabel, money, relativeDay, regionName } from "../format.js";
import { icon } from "../icons.js";
import { prefs } from "../store.js";
import { esc, statusChip } from "../ui.js";

export function masked(text) {
  return prefs.hideBalances ? "•••••" : text;
}

export function txIcon(item) {
  if (item.status.key === "failed") return `<span class="tx-icon failed">${icon("x")}</span>`;
  if (item.origin === "DEPOSITO") return `<span class="tx-icon in">${icon("deposit")}</span>`;
  if (item.origin === "LEVANTAMENTO") return `<span class="tx-icon">${icon("withdraw")}</span>`;
  if (item.direction === "in") return `<span class="tx-icon in">${icon("arrowDown")}</span>`;
  return `<span class="tx-icon out">${icon(item.kind === "DISTRIBUIDA" ? "globe" : "arrowUp")}</span>`;
}

export function amountHtml(item) {
  const signed = item.direction === "in" ? item.amount : -item.amount;
  const cls = item.status.key === "failed" ? "muted" : item.direction === "in" ? "amount-in" : "";
  const strike = item.status.key === "failed" ? "text-decoration:line-through;" : "";
  return `<span class="amount num ${cls}" style="${strike}">${esc(masked(money(signed, item.currency, { sign: true })))}</span>`;
}

export function activitySub(item) {
  const parts = [relativeDay(item.date)];
  if (item.counterparty && !item.title.includes(iban(item.counterparty))) parts.push(ibanShort(item.counterparty));
  if (item.kind && item.origin === "TRANSFERENCIA") parts.push(kindLabel(item.kind));
  return parts.join(" · ");
}

export function activityRow(item) {
  return `
    <a class="list-item" href="#/tx/${encodeURIComponent(item.txId)}">
      ${txIcon(item)}
      <span class="grow">
        <span class="title">${esc(item.title)}</span>
        <span class="sub">${esc(activitySub(item))}</span>
      </span>
      <span style="text-align:right">
        ${amountHtml(item)}
        ${item.status.key !== "done" ? `<br>${statusChip(item.status)}` : ""}
      </span>
    </a>`;
}

export function accountCard(a, { href = true } = {}) {
  const tag = href ? "a" : "div";
  return `
    <${tag} class="account-card" ${href ? `href="#/accounts/${encodeURIComponent(a.iban)}"` : ""}>
      <div class="row between">
        <span class="cur">${esc(a.currency)}</span>
        <span class="chip ${a.status === "ATIVA" ? "status-done" : "status-failed"}">${a.status === "ATIVA" ? "Ativa" : "Bloqueada"}</span>
      </div>
      <div class="bal num">${esc(masked(money(a.balance, a.currency)))}</div>
      <div class="iban mono">${esc(iban(a.iban))}</div>
      <div class="hint" style="margin-top:10px">Conta à ordem · ${regionName(a.region)}</div>
    </${tag}>`;
}

export function pageHead(title, subtitle = "", actions = "") {
  return `<div class="page-head"><div><h1>${esc(title)}</h1>${subtitle ? `<p>${subtitle}</p>` : ""}</div>${actions ? `<div class="row wrap">${actions}</div>` : ""}</div>`;
}
