// Resumo do cliente.
//  [ património (compacto, 7)          ] [ limite diário (5)       ]
//  [ as suas contas: um cartão por conta, qualquer região e moeda (12) ]
//  [ últimos movimentos (8)             ] [ câmbio + enviar a (4)  ]
// Uma só ação de transferir (no topo). Sem lógica de negócio: só leitura das APIs.
import { api, session } from "../api.js";
import { activity, convert, fxRates, myAccounts } from "../data.js";
import { iban as fmtIban, initials, money, number, regionName, REGIONS } from "../format.js";
import { icon } from "../icons.js";
import { beneficiaries, prefs } from "../store.js";
import { $, $$, esc } from "../ui.js";
import { activityRow, masked } from "./common.js";

function greeting() {
  const h = new Date().getHours();
  return h < 6 ? "Boa noite" : h < 13 ? "Bom dia" : h < 20 ? "Boa tarde" : "Boa noite";
}

const STATUS = { ATIVA: "Ativa", BLOQUEADA: "Bloqueada", ENCERRADA: "Encerrada" };

export async function render({ root, claims }) {
  const [accounts, rates, limits] = await Promise.all([
    myAccounts(), fxRates(), api("/me/limits").catch(() => null), beneficiaries.load().catch(() => []),
  ]);
  const home = REGIONS[claims.region]?.currency || "EUR";
  const name = (session.get()?.profile?.name || "").split(" ")[0];
  const open = accounts.filter((a) => a.status !== "ENCERRADA");
  if (!open.length) {
    root.innerHTML = `<div class="panel"><div class="empty"><div class="tx-icon">${icon("wallet")}</div><h3>Ainda não tem contas</h3><p>A sua conta é aberta assim que a verificação de identidade for aprovada.</p></div></div>`;
    return;
  }
  const total = open.reduce((s, a) => s + (convert(a.balance, a.currency, home, rates) ?? 0), 0);
  const regions = [...new Set(open.map((a) => a.region))];
  const favs = beneficiaries.all().slice(0, 4);

  // Limite diário (por cliente, em EUR, somando todas as contas)
  let limitHtml = `<div class="empty-sm">Limites indisponíveis de momento.</div>`;
  if (limits) {
    const lim = Number(limits.daily_limit_eur), sent = Number(limits.sent_today_eur);
    const pct = lim ? Math.min(100, Math.round((sent / lim) * 100)) : 0;
    const others = Object.entries(limits.remaining_by_currency || {}).filter(([c]) => c !== "EUR");
    limitHtml = `
      <div class="limit-figure"><b class="num">${esc(masked(money(limits.remaining_eur, "EUR")))}</b><span>ainda pode enviar hoje</span></div>
      <div><div class="meter ${pct >= 100 ? "full" : pct >= 80 ? "warn" : ""}" role="meter" aria-valuemin="0" aria-valuemax="${lim}" aria-valuenow="${sent}" aria-label="Limite diário usado"><i style="width:${pct}%"></i></div>
        <div class="limit-legend" style="margin-top:6px"><span>Enviado hoje ${esc(masked(money(sent, "EUR")))}</span><span>Limite ${esc(money(lim, "EUR"))}</span></div></div>
      ${others.length ? `<p class="hint num">≈ ${others.map(([c, v]) => esc(masked(money(v, c)))).join(" · ")} nas suas outras moedas</p>` : ""}`;
  }

  root.innerHTML = `
    <div class="page-head">
      <div><h1>${esc(greeting())}${name ? `, ${esc(name)}` : ""}</h1>
        <p>${esc(new Intl.DateTimeFormat("pt-PT", { weekday: "long", day: "numeric", month: "long" }).format(new Date()))} · ${open.length} ${open.length === 1 ? "conta" : "contas"} em ${regions.map((r) => esc(REGIONS[r]?.city || r)).join(", ")}</p></div>
      <div class="row"><button class="btn btn-secondary" id="hide">${icon(prefs.hideBalances ? "eye" : "eyeOff")} ${prefs.hideBalances ? "Mostrar saldos" : "Ocultar saldos"}</button>
        <a class="btn btn-primary" href="#/transfer">${icon("transfer")} Nova transferência</a></div>
    </div>

    <div class="bento">
      <section class="hero compact c-7" aria-labelledby="total-label">
        <div>
          <div class="h-label" id="total-label">${icon("wallet")} Património total</div>
          <div class="h-value">${esc(masked(money(total, home)))}</div>
          <div class="h-meta">${open.length} ${open.length === 1 ? "conta" : "contas"} · ${regions.length} ${regions.length === 1 ? "região" : "regiões"} · convertido para ${esc(home)} ao câmbio do dia</div>
        </div>
        <div class="h-stats" id="stats">
          ${["Entradas · 30 dias", "Saídas · 30 dias", "Movimentos · 30 dias"].map((l) => `<div><span>${l}</span><b class="skeleton">000,00 €</b></div>`).join("")}
        </div>
      </section>
      <section class="panel c-5 limit-card">
        <div class="panel-head"><div><h3>Limite diário</h3><div class="sub">todas as suas contas somadas, em EUR</div></div></div>
        <div class="panel-body">${limitHtml}</div>
        <div class="panel-foot"><span>Máx. ${limits ? esc(money(limits.max_transfer_eur, "EUR")) : "—"} por transferência</span><span title="Transferências entre as suas contas não contam para o limite">${icon("info")} Entre contas próprias não conta</span></div>
      </section>
    </div>

    <section class="panel mt">
      <div class="panel-head"><div><h3>As suas contas</h3><div class="sub">saldo na moeda de cada conta e o equivalente em ${esc(home)}</div></div><a class="link-btn" href="#/accounts">Ver detalhes</a></div>
      <div class="acct-grid">${accounts.map((a) => {
        const conv = a.currency !== home ? convert(a.balance, a.currency, home, rates) : null;
        return `
        <a class="acct-card ${a.status === "ENCERRADA" ? "closed" : ""}" href="#/accounts/${encodeURIComponent(a.iban)}">
          <div class="a-top"><span class="region-tag">${esc(a.region)}</span>
            <span class="grow"><b>${esc(regionName(a.region))} · ${esc(REGIONS[a.region]?.city || "")}</b><span class="mono">${esc(fmtIban(a.iban))}</span></span>
            <span class="cur-badge">${esc(a.currency)}</span></div>
          <div><div class="a-bal">${esc(masked(money(a.balance, a.currency)))}</div>
            <div class="a-conv">${conv != null ? `≈ ${esc(masked(money(conv, home)))}` : "&nbsp;"}</div></div>
          <div class="a-foot"><span class="chip ${a.status === "ATIVA" ? "status-done" : a.status === "ENCERRADA" ? "" : "status-failed"}">${esc(STATUS[a.status] || a.status)}</span>
            <span>Limite da conta ${esc(number(a.daily_limit, 0))} ${esc(a.currency)}/dia</span></div>
        </a>`; }).join("")}</div>
    </section>

    <div class="bento mt">
      <section class="panel c-8">
        <div class="panel-head"><h3>Últimos movimentos</h3><a class="link-btn" href="#/history">Ver todos</a></div>
        <div class="panel-body flush" id="recent">${[1, 2, 3, 4, 5].map(() => `<div class="list-item"><span class="tx-icon skeleton"></span><span class="grow"><span class="title skeleton">Transferência</span></span></div>`).join("")}</div>
      </section>
      <div class="c-4 stack-gap">
        <section class="panel">
          <div class="panel-head"><div><h3>Câmbio do dia</h3><div class="sub">aplicado às transferências entre moedas</div></div></div>
          <div class="panel-body flush">${[["EUR", "USD"], ["USD", "EUR"], ["EUR", "MZN"], ["USD", "MZN"]].filter(([b, q]) => rates[b]?.[q]).map(([b, q]) => `
            <div class="fx-row"><span class="cur-badge">${b}</span><span class="soft">→ ${q}</span><b class="num">${esc(number(rates[b][q], 4))}</b></div>`).join("")}</div>
        </section>
        <section class="panel">
          <div class="panel-head"><h3>Enviar a</h3><a class="link-btn" href="#/beneficiaries">Gerir</a></div>
          <div class="rows">${favs.map((b) => `
            <a class="r-item" href="#/transfer?to=${encodeURIComponent(b.iban)}&name=${encodeURIComponent(b.name)}">
              <span class="avatar" style="width:36px;height:36px;font-size:.78rem">${esc(initials(b.name))}</span>
              <span style="min-width:0"><span class="r-title">${esc(b.name)}</span><span class="r-sub mono">${esc(fmtIban(b.iban))}</span></span>
              <span class="r-end soft">${icon("arrowRight")}</span></a>`).join("") || `<div class="empty-sm">Guarde beneficiários para os encontrar aqui.<br><a href="#/beneficiaries">Adicionar beneficiário</a></div>`}</div>
        </section>
      </div>
    </div>`;

  $("#hide", root).addEventListener("click", () => { prefs.hideBalances = !prefs.hideBalances; render({ root, claims }); });

  const items = await activity(accounts, { limit: 100 });
  $("#recent", root).innerHTML = items.length ? `<ul class="list">${items.slice(0, 7).map((i) => `<li>${activityRow(i)}</li>`).join("")}</ul>` : `<div class="empty-sm">Ainda não há movimentos.</div>`;

  const since = Date.now() - 30 * 86400000;
  const recent = items.filter((i) => new Date(i.date).getTime() >= since && i.status.key !== "failed");
  const sum = (dir) => recent.filter((i) => i.direction === dir).reduce((s, i) => s + (convert(i.amount, i.currency, home, rates) ?? 0), 0);
  const values = [masked(money(sum("in"), home)), masked(money(sum("out"), home)), `${recent.length}`];
  $$("#stats b", root).forEach((b, i) => { b.className = ""; b.textContent = values[i]; });
}
