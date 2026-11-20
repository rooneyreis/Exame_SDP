// Centro de notificações (todos os perfis): derivadas dos registos reais, com filtro e estado "lida".
import { dateTime } from "../format.js";
import { icon } from "../icons.js";
import { markRead, notifications, unread } from "../notify.js";
import { $, $$, esc } from "../ui.js";
import { pageHead } from "./common.js";

const KINDS = [["all", "Todas"], ["unread", "Por ler"], ["bad", "Críticas"], ["warn", "A requerer ação"], ["good", "Concluídas"], ["info", "Informação"]];

export async function render({ root, navigate }) {
  let items = await notifications({ fresh: true });
  let filter = "all";
  function draw() {
    const un = new Set(unread(items).map((n) => n.id));
    const list = items.filter((n) => filter === "all" || (filter === "unread" ? un.has(n.id) : n.kind === filter));
    const counts = Object.fromEntries(KINDS.map(([k]) => [k, k === "all" ? items.length : k === "unread" ? un.size : items.filter((n) => n.kind === k).length]));
    root.innerHTML = `
      ${pageHead("Notificações", "Eventos relevantes das últimas duas semanas, gerados a partir das operações reais.",
        `<button class="btn btn-secondary" id="read-all" ${un.size ? "" : "disabled"}>${icon("check")} Marcar todas como lidas</button>`)}
      <div class="bento">
        <section class="panel c-8">
          <div class="filters">${KINDS.map(([k, l]) => `<button class="chip-filter" data-f="${k}" aria-pressed="${k === filter}">${l} <span class="n">${counts[k]}</span></button>`).join("")}</div>
          <div class="notif-list" style="max-height:none">${list.map((n) => `
            <a class="notif ${un.has(n.id) ? "unread" : ""}" href="#${esc(n.href)}" data-id="${esc(n.id)}">
              <span class="ic ${n.kind}">${icon(n.icon)}</span><span style="min-width:0"><b>${esc(n.title)}</b><div class="t">${esc(n.text)}</div></span>
              <time>${esc(dateTime(n.at))}</time></a>`).join("") || `<div class="empty"><div class="tx-icon in">${icon("check")}</div><h3>Tudo em dia</h3><p>Não há notificações nesta categoria.</p></div>`}</div>
        </section>
        <aside class="c-4 stack-gap">
          <section class="panel"><div class="metric-strip" style="--n:2">
            <div class="metric"><span class="m-label">${icon("bell")} Por ler</span><span class="m-value">${un.size}</span></div>
            <div class="metric"><span class="m-label">${icon("alert")} Críticas</span><span class="m-value">${counts.bad}</span></div></div></section>
          <section class="panel"><div class="panel-head"><h3>Como funcionam</h3></div><div class="panel-body">
            <p class="soft" style="font-size:.88rem">As notificações são calculadas a partir das operações e registos reais do seu perfil: transferências, aprovações, alertas de auditoria e estado dos sistemas. O estado “lida” fica guardado neste dispositivo.</p>
          </div></section>
        </aside>
      </div>`;
    $$("[data-f]", root).forEach((b) => b.addEventListener("click", () => { filter = b.dataset.f; draw(); }));
    $("#read-all", root).addEventListener("click", () => { markRead(items.map((n) => n.id)); draw(); window.dispatchEvent(new Event("gs:notif")); });
    $$("[data-id]", root).forEach((a) => a.addEventListener("click", () => markRead([a.dataset.id])));
  }
  draw();
  void navigate;
}
