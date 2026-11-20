// Arranque, router (hash) e estrutura da aplicação:
//   barra lateral recolhível · cabeçalho (trilho, pesquisa global, notificações, perfil) · conteúdo
//   barra de separadores no telemóvel.
import { logout, session } from "./api.js";
import { initials, relativeDay, roleLabel, regionName } from "./format.js";
import { icon, LOGO } from "./icons.js";
import { markRead, notifications, unread } from "./notify.js";
import { openSearch } from "./search.js";
import { applyTheme, prefs } from "./store.js";
import { $, $$, errorState, esc, loading, popover, toast } from "./ui.js";

import * as loginView from "./views/login.js";
import * as registerView from "./views/register.js";
import * as dashboardView from "./views/dashboard.js";
import * as transferView from "./views/transfer.js";
import * as historyView from "./views/history.js";
import * as receiptView from "./views/receipt.js";
import * as accountsView from "./views/accounts.js";
import * as beneficiariesView from "./views/beneficiaries.js";
import * as profileView from "./views/profile.js";
import * as opsView from "./views/ops.js";
import * as auditView from "./views/audit.js";
import * as adminView from "./views/admin.js";
import * as adminHomeView from "./views/admin-home.js";
import * as requestsView from "./views/requests.js";
import * as transfersAllView from "./views/transfers-all.js";
import * as accountsAdminView from "./views/accounts-admin.js";
import * as usersView from "./views/users.js";
import * as settingsView from "./views/settings.js";
import * as beneficiariesAdminView from "./views/beneficiaries-admin.js";
import * as auditEventsView from "./views/audit-events.js";
import * as auditHomeView from "./views/audit-home.js";
import * as opsHomeView from "./views/ops-home.js";
import * as opsTransferView from "./views/ops-transfer.js";
import * as reportsView from "./views/reports.js";
import * as notificationsView from "./views/notifications.js";

const CLIENT = ["cliente"];
const STAFF = ["operador", "auditor", "admin"];
const ALL = [...CLIENT, ...STAFF];

const ROUTES = [
  { path: "/login", view: loginView, public: true, title: "Entrar" },
  { path: "/register", view: registerView, public: true, title: "Abrir conta" },
  // Cliente
  { path: "/dashboard", view: dashboardView, roles: CLIENT, title: "Resumo" },
  { path: "/transfer", view: transferView, roles: CLIENT, title: "Transferir" },
  { path: "/history", view: historyView, roles: CLIENT, title: "Movimentos" },
  { path: "/accounts", view: accountsView, roles: CLIENT, title: "Contas" },
  { path: "/beneficiaries", view: beneficiariesView, roles: CLIENT, title: "Beneficiários" },
  // Comuns
  { path: "/tx/:id", view: receiptView, roles: ALL, title: "Comprovativo" },
  { path: "/accounts/:iban", view: accountsView, roles: ["cliente", "operador", "auditor", "admin"], title: "Conta" },
  { path: "/profile", view: profileView, roles: ALL, title: "Definições" },
  { path: "/notifications", view: notificationsView, roles: ALL, title: "Notificações" },
  // Operador
  { path: "/ops", view: opsHomeView, roles: ["operador"], title: "Painel de operações" },
  { path: "/ops/transfer", view: opsTransferView, roles: ["operador"], title: "Nova transferência" },
  { path: "/ops/requests", view: requestsView, roles: ["operador"], title: "Operações" },
  { path: "/ops/kyc", view: opsView, roles: ["operador", "admin"], title: "Abertura de contas" },
  { path: "/ops/accounts", view: opsView, roles: ["operador", "auditor"], title: "Contas e caixa" },
  { path: "/ops/beneficiaries", view: beneficiariesAdminView, roles: ["operador"], title: "Beneficiários de clientes" },
  // Auditor
  { path: "/audit", view: auditHomeView, roles: ["auditor"], title: "Painel de auditoria" },
  { path: "/audit/events", view: auditEventsView, roles: ["auditor", "admin"], title: "Registos de auditoria" },
  { path: "/audit/compliance", view: auditView, roles: ["auditor", "admin"], title: "Conformidade" },
  { path: "/audit/requests", view: requestsView, roles: ["auditor"], title: "Pedidos e aprovações" },
  { path: "/audit/beneficiaries", view: beneficiariesAdminView, roles: ["auditor"], title: "Beneficiários" },
  // Administrador
  { path: "/admin", view: adminHomeView, roles: ["admin"], title: "Visão geral" },
  { path: "/admin/approvals", view: requestsView, roles: ["admin"], title: "Aprovações" },
  { path: "/admin/users", view: usersView, roles: ["admin"], title: "Utilizadores e perfis" },
  { path: "/admin/settings", view: settingsView, roles: STAFF, title: "Limites" },
  { path: "/admin/beneficiaries", view: beneficiariesAdminView, roles: ["admin"], title: "Beneficiários" },
  { path: "/admin/infra", view: adminView, roles: ["admin"], title: "Infraestrutura" },
  { path: "/reports", view: reportsView, roles: ["admin", "auditor"], title: "Relatórios" },
  { path: "/admin/transfers", view: transfersAllView, roles: STAFF, title: "Transferências" },
  { path: "/admin/accounts", view: accountsAdminView, roles: ["admin", "auditor"], title: "Contas" },
];

export const NAV = {
  cliente: [
    { group: "Banca", items: [
      { to: "/dashboard", icon: "home", label: "Resumo" },
      { to: "/accounts", icon: "wallet", label: "Contas" },
      { to: "/transfer", icon: "transfer", label: "Transferir" },
      { to: "/history", icon: "history", label: "Movimentos" },
      { to: "/beneficiaries", icon: "users", label: "Beneficiários" },
    ] },
    { group: "Conta", items: [
      { to: "/notifications", icon: "bell", label: "Notificações" },
      { to: "/profile", icon: "settings", label: "Definições" },
    ] },
  ],
  operador: [
    { group: "Transferências", items: [
      { to: "/ops", icon: "home", label: "Painel" },
      { to: "/ops/transfer", icon: "plus", label: "Nova transferência" },
      { to: "/ops/requests", icon: "clock", label: "Operações" },
      { to: "/admin/transfers", icon: "history", label: "Histórico" },
    ] },
    { group: "Clientes", items: [
      { to: "/ops/beneficiaries", icon: "users", label: "Beneficiários" },
      { to: "/ops/accounts", icon: "wallet", label: "Contas e caixa" },
      { to: "/ops/kyc", icon: "check", label: "Abertura de contas" },
    ] },
    { group: "Conta", items: [
      { to: "/notifications", icon: "bell", label: "Notificações" },
      { to: "/admin/settings", icon: "info", label: "Limites" },
      { to: "/profile", icon: "settings", label: "Definições" },
    ] },
  ],
  auditor: [
    { group: "Fiscalização", items: [
      { to: "/audit", icon: "home", label: "Painel" },
      { to: "/admin/transfers", icon: "transfer", label: "Transferências" },
      { to: "/audit/requests", icon: "clock", label: "Aprovações" },
      { to: "/audit/events", icon: "doc", label: "Registos" },
      { to: "/reports", icon: "chart", label: "Relatórios" },
      { to: "/audit/compliance", icon: "shield", label: "Conformidade" },
    ] },
    { group: "Consulta", items: [
      { to: "/admin/accounts", icon: "wallet", label: "Contas" },
      { to: "/audit/beneficiaries", icon: "users", label: "Beneficiários" },
      { to: "/admin/settings", icon: "info", label: "Limites" },
    ] },
    { group: "Conta", items: [
      { to: "/notifications", icon: "bell", label: "Notificações" },
      { to: "/profile", icon: "settings", label: "Definições" },
    ] },
  ],
  admin: [
    { group: "Instituição", items: [
      { to: "/admin", icon: "home", label: "Visão geral" },
      { to: "/admin/approvals", icon: "check", label: "Aprovações" },
      { to: "/admin/transfers", icon: "transfer", label: "Transferências" },
      { to: "/admin/accounts", icon: "wallet", label: "Contas" },
      { to: "/reports", icon: "chart", label: "Relatórios" },
    ] },
    { group: "Gestão", items: [
      { to: "/admin/users", icon: "users", label: "Utilizadores" },
      { to: "/admin/beneficiaries", icon: "star", label: "Beneficiários" },
      { to: "/admin/settings", icon: "sliders", label: "Limites" },
      { to: "/ops/kyc", icon: "key", label: "Abertura de contas" },
    ] },
    { group: "Supervisão", items: [
      { to: "/audit/events", icon: "doc", label: "Registos" },
      { to: "/audit/compliance", icon: "shield", label: "Conformidade" },
      { to: "/admin/infra", icon: "server", label: "Infraestrutura" },
    ] },
    { group: "Conta", items: [
      { to: "/notifications", icon: "bell", label: "Notificações" },
      { to: "/profile", icon: "settings", label: "Definições" },
    ] },
  ],
};

const HOME = { cliente: "/dashboard", operador: "/ops", auditor: "/audit", admin: "/admin" };

function match(path) {
  for (const r of ROUTES) {
    const keys = [];
    const re = new RegExp("^" + r.path.replace(/:(\w+)/g, (_, k) => { keys.push(k); return "([^/]+)"; }) + "$");
    const m = re.exec(path);
    if (m) return { route: r, params: Object.fromEntries(keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) };
  }
  return null;
}

export function navigate(path) {
  if (location.hash !== `#${path}`) location.hash = path;
  else render();
}

function currentPath() { return (location.hash.replace(/^#/, "") || "/").split("?")[0]; }
export function query() { return new URLSearchParams(location.hash.split("?")[1] || ""); }

function sectionOf(role, path) {
  for (const g of NAV[role] || []) for (const i of g.items) if (i.to === path) return g.group;
  return null;
}

function shell(claims) {
  const name = session.get()?.profile?.name || roleLabel(claims.role);
  const nav = NAV[claims.role] || [];
  const tabs = nav.flatMap((g) => g.items).filter((i) => i.to !== "/notifications").slice(0, 5);
  const collapsed = localStorage.getItem("gs.sb") === "1";
  return `
  <div class="app ${collapsed ? "sb-collapsed" : ""}">
    <aside class="sidebar" id="sidebar" aria-label="Navegação principal">
      <a class="brand" href="#${HOME[claims.role]}" title="Global Scale">
        <span class="brand-mark">${LOGO}</span>
        <span class="brand-text"><span class="brand-name">Global Scale</span><span class="brand-sub">${claims.role === "cliente" ? "Banca Digital" : "Back-office"}</span></span>
      </a>
      <nav class="nav">
        ${nav.map((g) => `<div class="nav-label">${esc(g.group)}</div>
          ${g.items.map((i) => `<a href="#${i.to}" data-nav="${i.to}" title="${esc(i.label)}">${icon(i.icon)}<span>${esc(i.label)}</span>${i.to === "/notifications" ? `<b class="count" id="nav-notif" hidden></b>` : ""}</a>`).join("")}`).join("")}
      </nav>
      <div class="sidebar-foot">
        <button class="collapse-btn" id="collapse" title="Recolher / expandir a barra lateral" aria-label="Recolher a barra lateral">${icon("chevronLeft")}<span>Recolher</span></button>
        <div class="user-chip">
          <span class="avatar" title="${esc(name)}">${esc(initials(name))}</span>
          <span class="who"><b>${esc(name)}</b><span>${esc(claims.role === "cliente" ? `Cliente · ${regionName(claims.region)}` : roleLabel(claims.role))}</span></span>
          <button class="btn btn-ghost btn-icon" id="logout" aria-label="Terminar sessão" title="Terminar sessão">${icon("logout")}</button>
        </div>
      </div>
    </aside>
    <div class="main">
      <header class="topbar" id="topbar">
        <button class="btn btn-ghost btn-icon menu-btn" id="menu" aria-label="Abrir menu" aria-controls="sidebar">${icon("menu")}</button>
        <nav class="crumbs" id="crumbs" aria-label="Localização"></nav>
        <span class="spacer"></span>
        <button class="search-trigger hide-sm" id="search" aria-label="Pesquisa global (Ctrl+K)">${icon("search")}<span>Pesquisar</span><span class="kbd">Ctrl K</span></button>
        <button class="icon-btn show-sm" id="search-sm" aria-label="Pesquisar">${icon("search")}</button>
        <button class="icon-btn" id="bell" aria-label="Notificações" aria-haspopup="menu">${icon("bell")}<span class="badge" id="bell-badge" hidden></span></button>
        <button class="profile-btn" id="profile" aria-label="Menu do perfil" aria-haspopup="menu"><span class="avatar">${esc(initials(name))}</span>${icon("chevronDown")}</button>
      </header>
      <main class="content" id="view" tabindex="-1"></main>
    </div>
    <nav class="tabbar" style="--tabs:${tabs.length}" aria-label="Navegação rápida">
      ${tabs.map((i) => `<a href="#${i.to}" data-nav="${i.to}">${icon(i.icon)}<span>${esc(i.label.split(" ")[0])}</span></a>`).join("")}
    </nav>
  </div>`;
}

async function doLogout() {
  await logout();
  toast("Sessão terminada com segurança", "info");
  navigate("/login");
}

function isDark() {
  return document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
}

function bindShell(claims) {
  const app = $(".app");
  $("#logout")?.addEventListener("click", doLogout);
  $("#collapse")?.addEventListener("click", () => {
    const on = !app.classList.contains("sb-collapsed");
    app.classList.toggle("sb-collapsed", on);
    try { localStorage.setItem("gs.sb", on ? "1" : "0"); } catch { /* ignore */ }
    window.dispatchEvent(new Event("resize"));
  });
  $("#menu")?.addEventListener("click", () => {
    $("#sidebar").classList.add("open");
    const scrim = document.createElement("div");
    scrim.className = "sidebar-scrim";
    scrim.addEventListener("click", closeMenu);
    document.body.append(scrim);
  });
  const search = () => openSearch({ navigate, nav: NAV[claims.role] || [], role: claims.role });
  $("#search")?.addEventListener("click", search);
  $("#search-sm")?.addEventListener("click", search);

  $("#profile")?.addEventListener("click", (e) => {
    const name = session.get()?.profile?.name || "";
    const pop = popover(e.currentTarget, `
      <div class="menu-head"><b>${esc(name)}</b><div class="hint">${esc(session.get()?.profile?.email || "")}</div><div class="hint">${esc(roleLabel(claims.role))}</div></div>
      <div class="menu-sep"></div>
      <a class="menu-item" href="#/profile">${icon("settings")} Definições e segurança</a>
      <a class="menu-item" href="#/notifications">${icon("bell")} Notificações</a>
      <button class="menu-item" data-act="theme">${icon(isDark() ? "sun" : "moon")} ${isDark() ? "Tema claro" : "Tema escuro"}</button>
      <button class="menu-item" data-act="search">${icon("search")} Pesquisa global <span class="kbd" style="margin-left:auto">Ctrl K</span></button>
      <div class="menu-sep"></div>
      <button class="menu-item danger" data-act="logout">${icon("logout")} Terminar sessão</button>`, { className: "" });
    pop.el.style.width = "270px";
    pop.el.addEventListener("click", (ev) => {
      const act = ev.target.closest("[data-act]")?.dataset.act;
      if (ev.target.closest("a")) pop.close();
      if (act === "theme") { prefs.theme = isDark() ? "light" : "dark"; pop.close(); }
      if (act === "search") { pop.close(); search(); }
      if (act === "logout") { pop.close(); doLogout(); }
    });
  });

  $("#bell")?.addEventListener("click", async (e) => {
    const anchor = e.currentTarget;
    const items = await notifications();
    const un = new Set(unread(items).map((n) => n.id));
    const pop = popover(anchor, `
      <div class="pop-head"><b>Notificações</b>${un.size ? `<button class="link-btn" data-act="read">Marcar como lidas</button>` : ""}</div>
      <div class="notif-list">${items.slice(0, 8).map((n) => `
        <a class="notif ${un.has(n.id) ? "unread" : ""}" href="#${esc(n.href)}" data-id="${esc(n.id)}">
          <span class="ic ${n.kind}">${icon(n.icon)}</span><span style="min-width:0"><b>${esc(n.title)}</b><div class="t">${esc(n.text)}</div></span>
          <time>${esc(relativeDay(n.at).replace(/, \d\d:\d\d$/, ""))}</time></a>`).join("") || `<div class="empty-sm">Sem notificações.</div>`}</div>
      <div class="panel-foot"><a href="#/notifications">Ver todas</a><span>${items.length} no total</span></div>`, { className: "notif-pop" });
    pop.el.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-act='read']")) { markRead(items.map((n) => n.id)); pop.close(); refreshBadge(); return; }
      const a = ev.target.closest("a");
      if (a) { if (a.dataset.id) markRead([a.dataset.id]); pop.close(); refreshBadge(); }
    });
  });

  // cabeçalho ganha uma linha subtil quando o conteúdo passa por baixo
  const top = $("#topbar");
  window.addEventListener("scroll", () => top?.classList.toggle("scrolled", window.scrollY > 4), { passive: true });
}

export async function refreshBadge() {
  const items = await notifications().catch(() => []);
  const n = unread(items).length;
  const badge = $("#bell-badge"), navCount = $("#nav-notif");
  if (badge) { badge.hidden = !n; badge.textContent = n > 9 ? "9+" : String(n); }
  if (navCount) { navCount.hidden = !n; navCount.textContent = n > 99 ? "99+" : String(n); }
}

function closeMenu() {
  $("#sidebar")?.classList.remove("open");
  $$(".sidebar-scrim").forEach((s) => s.remove());
}

let renderSeq = 0;

async function render() {
  const seq = ++renderSeq;
  const path = currentPath();
  const claims = session.claims;
  const loggedIn = claims && claims.exp * 1000 > Date.now() - 60_000 && session.get()?.refresh;

  if (path === "/" || path === "") return navigate(loggedIn ? HOME[claims.role] || "/profile" : "/login");
  const found = match(path);
  if (!found) return navigate(loggedIn ? HOME[claims.role] : "/login");
  const { route, params } = found;

  const root = $("#root");
  if (route.public) {
    if (loggedIn && path === "/login") return navigate(HOME[claims.role]);
    root.innerHTML = `<div id="view"></div>`;
    root.dataset.role = "";
    document.title = `${route.title} · Global Scale`;
    await route.view.render({ root: $("#view"), params, navigate });
    return;
  }
  if (!loggedIn) {
    sessionStorage.setItem("gs.next", path);
    return navigate("/login");
  }
  if (!route.roles.includes(claims.role)) return navigate(HOME[claims.role]);

  if (!$(".app") || root.dataset.role !== claims.role || root.dataset.sub !== claims.sub) {
    root.innerHTML = shell(claims);
    root.dataset.role = claims.role;
    root.dataset.sub = claims.sub;
    bindShell(claims);
  }
  closeMenu();
  document.querySelectorAll(".popover").forEach((p) => p._close?.());
  $$("[data-nav]").forEach((a) => {
    const active = path === a.dataset.nav || (!["/admin", "/ops", "/audit"].includes(a.dataset.nav) && path.startsWith(a.dataset.nav + "/"));
    if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const section = sectionOf(claims.role, path);
  $("#crumbs").innerHTML = `${section ? `<span class="sec">${esc(section)}</span><span class="sep">›</span>` : ""}<span class="cur">${esc(route.title)}</span>`;
  document.title = `${route.title} · Global Scale`;

  const view = $("#view");
  view.innerHTML = loading();
  view.classList.remove("view-enter");
  try {
    await route.view.render({ root: view, params, claims, navigate, query: query(), path });
    if (seq !== renderSeq) return;
    void view.offsetWidth;
    view.classList.add("view-enter");
    window.scrollTo({ top: 0 });
  } catch (err) {
    if (seq === renderSeq) view.innerHTML = errorState(err);
    console.error(err);
  }
  refreshBadge();
}

window.addEventListener("hashchange", render);
window.addEventListener("gs:logout", () => {
  toast("A sua sessão expirou. Entre novamente.", "info");
  navigate("/login");
});
document.addEventListener("click", (e) => { if (e.target.closest("[data-reload]")) render(); });
document.addEventListener("keydown", (e) => {
  const claims = session.claims;
  if (!claims || !$(".app")) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
  if ((e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); openSearch({ navigate, nav: NAV[claims.role] || [], role: claims.role }); }
  else if (e.key === "/" && !typing) { e.preventDefault(); openSearch({ navigate, nav: NAV[claims.role] || [], role: claims.role }); }
});
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);

applyTheme();
render();
