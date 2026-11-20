import { session } from "../api.js";
import { areaChart } from "../chart.js";
import { activity, balanceSeries, convert, fxRates, movements, myAccounts } from "../data.js";
import { date, iban as fmtIban, money, number } from "../format.js";
import { icon } from "../icons.js";
import { prefs } from "../store.js";
import { $, $$, esc } from "../ui.js";
import { accountCard, activityRow, masked } from "./common.js";

function greeting() {
  const h = new Date().getHours();
  return h < 6 ? "Boa noite" : h < 13 ? "Bom dia" : h < 20 ? "Boa tarde" : "Boa noite";
}

export async function render({ root, claims }) {
  const [accounts, rates] = await Promise.all([myAccounts(), fxRates()]);
  const home = claims.region === "AM" ? "USD" : "EUR";
  const name = (session.get()?.profile?.name || "").split(" ")[0];

  if (!accounts.length) {
    root.innerHTML = `<div class="card"><div class="empty"><div class="tx-icon">${icon("wallet")}</div>
      <h3>Ainda não tem contas</h3><p>A sua conta é aberta assim que a verificação de identidade for aprovada.</p></div></div>`;
    return;
  }

  const total = accounts.reduce((s, a) => s + (convert(a.balance, a.currency, home, rates) ?? 0), 0);
  root.innerHTML = `
    <div class="page-head">
      <div><h1>${esc(greeting())}${name ? `, ${esc(name)}` : ""}</h1>
        <p>${esc(new Intl.DateTimeFormat("pt-PT", { weekday: "long", day: "numeric", month: "long" }).format(new Date()))}</p></div>
      <div class="row"><a class="btn btn-primary" href="#/transfer">${icon("transfer")} Nova transferência</a></div>
    </div>

    <div class="grid g-main">
      <section class="card card-pad balance-hero" aria-labelledby="total-label">
        <div class="row between">
          <span class="label" id="total-label">Património total</span>
          <button class="btn btn-sm btn-light" id="hide" aria-pressed="${prefs.hideBalances}">${icon(prefs.hideBalances ? "eye" : "eyeOff")} ${prefs.hideBalances ? "Mostrar" : "Ocultar"}</button>
        </div>
        <div class="big num">${esc(masked(money(total, home)))}</div>
        <div class="meta">${accounts.length} ${accounts.length === 1 ? "conta" : "contas"} · valor estimado em ${esc(home)} ao câmbio do dia</div>
        <div class="row wrap" style="margin-top:26px;margin-bottom:26px">
          <a class="btn btn-white" href="#/transfer">${icon("arrowUp")} Enviar</a>
          <a class="btn btn-light" href="#/accounts">${icon("wallet")} Contas</a>
          <a class="btn btn-light" href="#/history">${icon("history")} Movimentos</a>
        </div>
        <div class="hero-foot-row" style="margin-top:auto">
          <div><span>Conta principal</span><b class="mono">${esc(fmtIban(accounts[0].iban))}</b></div>
          <div><span>Centro de dados</span><b>${claims.region === "AM" ? "Nova Iorque" : "Lisboa"}</b></div>
          <div><span>Proteção</span><b>${icon("shield")} Ordens assinadas</b></div>
        </div>
      </section>

      <section class="card" aria-labelledby="fx-title">
        <div class="card-head"><h3 id="fx-title">Câmbio do dia</h3><span class="chip chip-outline">${icon("refresh")} ${esc(date(Date.now(), { day: "2-digit", month: "short" }))}</span></div>
        <ul class="list" style="margin-top:6px">
          ${[["EUR", "USD"], ["USD", "EUR"], ["EUR", "MZN"], ["USD", "MZN"]].filter(([b, q]) => rates[b]?.[q]).map(([b, q]) => `
            <li class="list-item"><span class="cur" style="display:inline-grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--surface-sunken);font-weight:700;font-size:.75rem">${b}</span>
              <span class="grow"><span class="title">${b} → ${q}</span><span class="sub">1 ${b} =</span></span>
              <span class="amount num">${esc(number(rates[b][q], 4))} ${q}</span></li>`).join("")}
        </ul>
      </section>
    </div>

    <div class="grid g-4 keep-2" style="margin-top:20px" id="kpis">
      ${["Entradas · 30 dias", "Saídas · 30 dias", "Transferências · 30 dias", "Internacionais · 30 dias"].map((l) => `
        <div class="card card-pad stat"><div class="label">${l}</div><div class="value skeleton">000,00 €</div><div class="delta skeleton">—</div></div>`).join("")}
    </div>

    <div class="grid g-main" style="margin-top:20px">
      <section class="card" aria-labelledby="chart-title">
        <div class="card-head">
          <div><h3 id="chart-title">Evolução do saldo</h3><p class="hint" id="chart-sub"></p></div>
          ${accounts.length > 1 ? `<div class="segmented" role="group" aria-label="Conta">${accounts.map((a, i) => `<button data-acc="${esc(a.iban)}" aria-pressed="${i === 0}">${esc(a.currency)} ${esc(a.iban.slice(-4))}</button>`).join("")}</div>` : ""}
        </div>
        <div id="chart"><div class="page-loading" style="min-height:220px"><span class="spinner"></span></div></div>
      </section>

      <section class="card" aria-labelledby="recent-title">
        <div class="card-head"><h3 id="recent-title">Atividade recente</h3><a class="link" href="#/history">Ver tudo</a></div>
        <div id="recent" style="margin-top:8px">${[1, 2, 3, 4].map(() => `<div class="list-item"><span class="tx-icon skeleton"></span><span class="grow"><span class="title skeleton">Transferência</span></span></div>`).join("")}</div>
      </section>
    </div>

    <h2 style="margin:32px 0 14px">As suas contas</h2>
    <div class="grid g-3">${accounts.map((a) => accountCard(a)).join("")}
      <a class="account-card" href="#/beneficiaries" style="display:flex;flex-direction:column;justify-content:center;align-items:flex-start;border-style:dashed">
        <span class="cur">${icon("users")}</span><div style="margin-top:16px;font-weight:600">Beneficiários</div>
        <div class="hint">Guarde as contas para onde transfere com frequência</div></a>
    </div>`;

  $("#hide", root).addEventListener("click", () => { prefs.hideBalances = !prefs.hideBalances; render({ root, claims }); });

  // Gráfico por conta
  const chartHost = $("#chart", root);
  async function drawChart(acc) {
    const ms = await movements(acc.iban, 200);
    $("#chart-sub", root).textContent = `${acc.currency} · conta ${acc.iban.slice(-4)} · últimos ${ms.length} movimentos`;
    areaChart(chartHost, balanceSeries(ms, acc.balance), acc.currency);
  }
  $$("[data-acc]", root).forEach((b) => b.addEventListener("click", () => {
    $$("[data-acc]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    drawChart(accounts.find((a) => a.iban === b.dataset.acc));
  }));
  drawChart(accounts[0]).catch(() => { chartHost.innerHTML = `<p class="empty">Não foi possível carregar o gráfico.</p>`; });

  // Atividade + indicadores
  const items = await activity(accounts, { limit: 100 });
  $("#recent", root).innerHTML = items.length
    ? `<ul class="list">${items.slice(0, 6).map((i) => `<li>${activityRow(i)}</li>`).join("")}</ul>`
    : `<div class="empty"><p>Ainda não há movimentos.</p></div>`;

  const since = Date.now() - 30 * 86400000;
  const recent = items.filter((i) => new Date(i.date).getTime() >= since && i.status.key !== "failed");
  const inSum = recent.filter((i) => i.direction === "in").reduce((s, i) => s + (convert(i.amount, i.currency, home, rates) ?? 0), 0);
  const outSum = recent.filter((i) => i.direction === "out").reduce((s, i) => s + (convert(i.amount, i.currency, home, rates) ?? 0), 0);
  const sent = items.filter((i) => new Date(i.date).getTime() >= since && i.origin === "TRANSFERENCIA" && i.direction === "out");
  const intl = sent.filter((i) => i.kind === "DISTRIBUIDA");
  const failed = sent.filter((i) => i.status.key === "failed").length;
  const pending = sent.filter((i) => i.status.key === "pending").length;
  const tiles = $$("#kpis .stat", root);
  const fill = (tile, value, delta) => {
    tile.querySelector(".value").className = "value num";
    tile.querySelector(".value").textContent = value;
    tile.querySelector(".delta").className = "delta";
    tile.querySelector(".delta").innerHTML = delta;
  };
  fill(tiles[0], masked(money(inSum, home)), `${recent.filter((i) => i.direction === "in").length} créditos`);
  fill(tiles[1], masked(money(outSum, home)), `${recent.filter((i) => i.direction === "out").length} débitos`);
  fill(tiles[2], String(sent.length), pending || failed ? `${pending} pendentes · ${failed} falhadas` : "todas processadas");
  fill(tiles[3], String(intl.length), intl.length ? `${Math.round((intl.length / Math.max(sent.length, 1)) * 100)}% do total enviado` : "sem envios internacionais");
}
