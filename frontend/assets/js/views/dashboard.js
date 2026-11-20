// Resumo do cliente: composição em grelha de 12 colunas.
//  [ património + indicadores 30 dias (8) ] [ ações rápidas + contas (4) ]
//  [ evolução do saldo (8)                ] [ câmbio do dia (4)          ]
//  [ atividade recente (8)                ] [ envio rápido (4)           ]
import { session } from "../api.js";
import { areaChart } from "../chart.js";
import { activity, balanceSeries, convert, fxRates, movements, myAccounts } from "../data.js";
import { iban as fmtIban, initials, money, number } from "../format.js";
import { icon } from "../icons.js";
import { beneficiaries, prefs } from "../store.js";
import { $, $$, esc } from "../ui.js";
import { activityRow, masked } from "./common.js";

function greeting() {
  const h = new Date().getHours();
  return h < 6 ? "Boa noite" : h < 13 ? "Bom dia" : h < 20 ? "Boa tarde" : "Boa noite";
}

export async function render({ root, claims }) {
  const [accounts, rates] = await Promise.all([myAccounts(), fxRates(), beneficiaries.load().catch(() => [])]);
  const home = claims.region === "AM" ? "USD" : "EUR";
  const name = (session.get()?.profile?.name || "").split(" ")[0];
  if (!accounts.length) {
    root.innerHTML = `<div class="panel"><div class="empty"><div class="tx-icon">${icon("wallet")}</div><h3>Ainda não tem contas</h3><p>A sua conta é aberta assim que a verificação de identidade for aprovada.</p></div></div>`;
    return;
  }
  const total = accounts.reduce((s, a) => s + (convert(a.balance, a.currency, home, rates) ?? 0), 0);
  const favs = beneficiaries.all().slice(0, 5);

  root.innerHTML = `
    <div class="page-head">
      <div><h1>${esc(greeting())}${name ? `, ${esc(name)}` : ""}</h1>
        <p>${esc(new Intl.DateTimeFormat("pt-PT", { weekday: "long", day: "numeric", month: "long" }).format(new Date()))} · ${accounts.length} ${accounts.length === 1 ? "conta" : "contas"} em ${claims.region === "AM" ? "Nova Iorque" : "Lisboa"}</p></div>
      <div class="row"><button class="btn btn-secondary" id="hide">${icon(prefs.hideBalances ? "eye" : "eyeOff")} ${prefs.hideBalances ? "Mostrar saldos" : "Ocultar saldos"}</button>
        <a class="btn btn-primary" href="#/transfer">${icon("transfer")} Nova transferência</a></div>
    </div>

    <div class="bento">
      <section class="hero c-8" aria-labelledby="total-label">
        <div>
          <div class="h-label" id="total-label">${icon("wallet")} Património total</div>
          <div class="h-value">${esc(masked(money(total, home)))}</div>
          <div class="h-meta">Valor estimado em ${esc(home)} ao câmbio do dia · conta principal <span class="mono">${esc(fmtIban(accounts[0].iban))}</span></div>
        </div>
        <div class="h-actions">
          <a class="btn btn-white" href="#/transfer">${icon("arrowUp")} Enviar</a>
          <a class="btn btn-light" href="#/history">${icon("history")} Movimentos</a>
        </div>
        <div class="h-stats" id="stats">
          ${["Entradas · 30 dias", "Saídas · 30 dias", "Transferências", "Internacionais"].map((l) => `<div><span>${l}</span><b class="skeleton">000,00 €</b></div>`).join("")}
        </div>
      </section>

      <div class="c-4 stack-gap">
        <section class="panel">
          <div class="panel-head"><h3>Ações rápidas</h3></div>
          <div class="panel-body"><div class="quick-actions">
            ${[["/transfer", "transfer", "out", "Transferir", "Enviar dinheiro"], ["/beneficiaries", "users", "", "Beneficiários", `${beneficiaries.all().length} guardados`],
               [`/accounts/${encodeURIComponent(accounts[0].iban)}`, "doc", "", "Extrato", "Movimentos e CSV"], ["/notifications", "bell", "", "Notificações", "Atividade recente"]]
              .map(([to, ic, cls, t, s]) => `<a class="qa" href="#${to}"><span class="tx-icon ${cls}">${icon(ic)}</span><div><b>${t}</b><span>${s}</span></div></a>`).join("")}
          </div></div>
        </section>
        <section class="panel">
          <div class="panel-head"><h3>Contas</h3><a class="link-btn" href="#/accounts">Ver todas</a></div>
          <div class="rows">${accounts.slice(0, 3).map((a) => `
            <a class="r-item" href="#/accounts/${encodeURIComponent(a.iban)}"><span class="cur-badge">${esc(a.currency)}</span>
              <span style="min-width:0"><span class="r-title mono">${esc(fmtIban(a.iban))}</span><span class="r-sub">${a.status === "ATIVA" ? "Ativa" : "Bloqueada"} · ${a.region === "EU" ? "Europa" : "América"}</span></span>
              <span class="r-end amount num">${esc(masked(money(a.balance, a.currency)))}</span></a>`).join("")}</div>
        </section>
      </div>
    </div>

    <div class="bento">
      <section class="panel c-8">
        <div class="panel-head"><div><h3>Evolução do saldo</h3><div class="sub" id="chart-sub"></div></div>
          ${accounts.length > 1 ? `<div class="tools"><div class="segmented" role="group" aria-label="Conta">${accounts.map((a, i) => `<button data-acc="${esc(a.iban)}" aria-pressed="${i === 0}">${esc(a.currency)} ${esc(a.iban.slice(-4))}</button>`).join("")}</div></div>` : ""}</div>
        <div class="panel-body flush" id="chart"><div class="page-loading" style="min-height:260px"><span class="spinner"></span></div></div>
      </section>
      <section class="panel c-4">
        <div class="panel-head"><div><h3>Câmbio do dia</h3><div class="sub">taxas aplicadas às transferências internacionais</div></div></div>
        <div class="panel-body flush">${[["EUR", "USD"], ["USD", "EUR"], ["EUR", "MZN"], ["USD", "MZN"], ["MZN", "EUR"]].filter(([b, q]) => rates[b]?.[q]).map(([b, q]) => `
          <div class="fx-row"><span class="cur-badge">${b}</span><span class="soft">→ ${q}</span><b class="num">${esc(number(rates[b][q], 4))}</b></div>`).join("")}</div>
        <div class="panel-foot"><span>${icon("info")} Sem comissões</span><span>Atualizado hoje</span></div>
      </section>
    </div>

    <div class="bento">
      <section class="panel c-8">
        <div class="panel-head"><h3>Atividade recente</h3><a class="link-btn" href="#/history">Ver todos os movimentos</a></div>
        <div class="panel-body flush" id="recent">${[1, 2, 3, 4, 5].map(() => `<div class="list-item"><span class="tx-icon skeleton"></span><span class="grow"><span class="title skeleton">Transferência</span></span></div>`).join("")}</div>
      </section>
      <section class="panel c-4">
        <div class="panel-head"><h3>Enviar a</h3><a class="link-btn" href="#/beneficiaries">Gerir</a></div>
        <div class="rows">${favs.map((b) => `
          <a class="r-item" href="#/transfer?to=${encodeURIComponent(b.iban)}&name=${encodeURIComponent(b.name)}">
            <span class="avatar" style="width:36px;height:36px;font-size:.78rem">${esc(initials(b.name))}</span>
            <span style="min-width:0"><span class="r-title">${esc(b.name)}</span><span class="r-sub mono">${esc(fmtIban(b.iban))}</span></span>
            <span class="r-end soft">${icon("arrowRight")}</span></a>`).join("") || `<div class="empty-sm">Guarde beneficiários para os encontrar aqui.<br><a href="#/beneficiaries">Adicionar beneficiário</a></div>`}</div>
      </section>
    </div>`;

  $("#hide", root).addEventListener("click", () => { prefs.hideBalances = !prefs.hideBalances; render({ root, claims }); });

  const chartHost = $("#chart", root);
  async function drawChart(acc) {
    const ms = await movements(acc.iban, 200);
    $("#chart-sub", root).textContent = `${acc.currency} · conta ${acc.iban.slice(-4)} · últimos ${ms.length} movimentos`;
    areaChart(chartHost, balanceSeries(ms, acc.balance), acc.currency, { height: 260 });
  }
  $$("[data-acc]", root).forEach((b) => b.addEventListener("click", () => {
    $$("[data-acc]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    drawChart(accounts.find((a) => a.iban === b.dataset.acc));
  }));
  drawChart(accounts[0]).catch(() => { chartHost.innerHTML = `<p class="empty-sm">Não foi possível carregar o gráfico.</p>`; });

  const items = await activity(accounts, { limit: 100 });
  $("#recent", root).innerHTML = items.length ? `<ul class="list">${items.slice(0, 6).map((i) => `<li>${activityRow(i)}</li>`).join("")}</ul>` : `<div class="empty-sm">Ainda não há movimentos.</div>`;

  const since = Date.now() - 30 * 86400000;
  const recent = items.filter((i) => new Date(i.date).getTime() >= since && i.status.key !== "failed");
  const sum = (dir) => recent.filter((i) => i.direction === dir).reduce((s, i) => s + (convert(i.amount, i.currency, home, rates) ?? 0), 0);
  const sent = items.filter((i) => new Date(i.date).getTime() >= since && i.origin === "TRANSFERENCIA" && i.direction === "out");
  const values = [masked(money(sum("in"), home)), masked(money(sum("out"), home)), `${sent.length}`, `${sent.filter((i) => i.kind === "DISTRIBUIDA").length}`];
  $$("#stats b", root).forEach((b, i) => { b.className = ""; b.textContent = values[i]; });
}
