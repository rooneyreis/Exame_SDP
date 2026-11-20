// Arranque, router (hash) e estrutura (barra lateral, barra superior, barra de separadores no telemóvel).
import { logout, session } from "./api.js";
import { initials, roleLabel } from "./format.js";
import { icon, LOGO } from "./icons.js";
import { applyTheme, prefs } from "./store.js";
import { $, $$, errorState, esc, loading, toast } from "./ui.js";

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

const CLIENT = ["cliente"];
const STAFF = ["operador", "auditor", "admin"];

// path, view, roles (undefined = público), título
const ROUTES = [
  { path: "/login", view: loginView, public: true, title: "Entrar" },
  { path: "/register", view: registerView, public: true, title: "Abrir conta" },
  { path: "/dashboard", view: dashboardView, roles: CLIENT, title: "Resumo" },
  { path: "/transfer", view: transferView, roles: CLIENT, title: "Transferir" },
  { path: "/history", view: historyView, roles: CLIENT, title: "Movimentos" },
  { path: "/tx/:id", view: receiptView, roles: ["cliente", "operador", "auditor", "admin"], title: "Comprovativo" },
  { path: "/accounts", view: accountsView, roles: CLIENT, title: "Contas" },
  { path: "/accounts/:iban", view: accountsView, roles: ["cliente", "operador", "auditor"], title: "Conta" },
  { path: "/beneficiaries", view: beneficiariesView, roles: CLIENT, title: "Beneficiários" },
  { path: "/profile", view: profileView, roles: [...CLIENT, ...STAFF], title: "Perfil e segurança" },
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
  { path: "/admin/settings", view: settingsView, roles: ["admin", "auditor", "operador"], title: "Limites" },
  { path: "/admin/beneficiaries", view: beneficiariesAdminView, roles: ["admin"], title: "Beneficiários" },
  { path: "/admin/infra", view: adminView, roles: ["admin"], title: "Infraestrutura" },
  // Partilhadas (o backend decide o que cada perfil pode fazer em cada uma)
  { path: "/admin/transfers", view: transfersAllView, roles: STAFF, title: "Transferências" },
  { path: "/admin/accounts", view: accountsAdminView, roles: ["admin", "auditor"], title: "Contas" },
];

const NAV = {
  cliente: [
    { group: "Banca", items: [
      { to: "/dashboard", icon: "home", label: "Resumo" },
      { to: "/accounts", icon: "wallet", label: "Contas" },
      { to: "/transfer", icon: "transfer", label: "Transferir" },
      { to: "/history", icon: "history", label: "Movimentos" },
      { to: "/beneficiaries", icon: "users", label: "Beneficiários" },
    ] },
    { group: "Conta", items: [{ to: "/profile", icon: "shield", label: "Perfil e segurança" }] },
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
      { to: "/admin/settings", icon: "info", label: "Limites" },
    ] },
    { group: "Conta", items: [{ to: "/profile", icon: "shield", label: "Perfil e segurança" }] },
  ],
  auditor: [
    { group: "Fiscalização", items: [
      { to: "/audit", icon: "home", label: "Painel" },
      { to: "/admin/transfers", icon: "transfer", label: "Transferências" },
      { to: "/audit/requests", icon: "clock", label: "Aprovações" },
      { to: "/audit/events", icon: "doc", label: "Registos" },
      { to: "/audit/compliance", icon: "shield", label: "Conformidade" },
    ] },
    { group: "Consulta", items: [
      { to: "/admin/accounts", icon: "wallet", label: "Contas" },
      { to: "/audit/beneficiaries", icon: "users", label: "Beneficiários" },
      { to: "/admin/settings", icon: "info", label: "Limites" },
    ] },
    { group: "Conta", items: [{ to: "/profile", icon: "user", label: "Perfil e segurança" }] },
  ],
  admin: [
    { group: "Instituição", items: [
      { to: "/admin", icon: "home", label: "Visão geral" },
      { to: "/admin/approvals", icon: "check", label: "Aprovações" },
      { to: "/admin/transfers", icon: "transfer", label: "Transferências" },
      { to: "/admin/accounts", icon: "wallet", label: "Contas" },
    ] },
    { group: "Gestão", items: [
      { to: "/admin/users", icon: "users", label: "Utilizadores" },
      { to: "/admin/beneficiaries", icon: "star", label: "Beneficiários" },
      { to: "/admin/settings", icon: "settings", label: "Limites" },
      { to: "/ops/kyc", icon: "key", label: "Abertura de contas" },
    ] },
    { group: "Supervisão", items: [
      { to: "/audit/events", icon: "doc", label: "Registos" },
      { to: "/audit/compliance", icon: "shield", label: "Conformidade" },
      { to: "/admin/infra", icon: "server", label: "Infraestrutura" },
    ] },
    { group: "Conta", items: [{ to: "/profile", icon: "user", label: "Perfil e segurança" }] },
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

function currentPath() {
  const h = location.hash.replace(/^#/, "") || "/";
  return h.split("?")[0];
}

export function query() {
  return new URLSearchParams(location.hash.split("?")[1] || "");
}

function shell(claims) {
  const name = session.get()?.profile?.name || session.get()?.profile?.email || roleLabel(claims.role);
  const nav = NAV[claims.role] || [];
  const tabs = nav.flatMap((g) => g.items).slice(0, 5);
  return `
  <div class="app">
    <aside class="sidebar" id="sidebar" aria-label="Navegação principal">
      <a class="brand" href="#${HOME[claims.role]}">
        <span class="brand-mark">${LOGO}</span>
        <span><span class="brand-name">Global Scale</span><br><span class="brand-sub">${claims.role === "cliente" ? "Banca Digital" : "Back-office"}</span></span>
      </a>
      <nav class="nav">
        ${nav.map((g) => `<div class="nav-label">${esc(g.group)}</div>
          ${g.items.map((i) => `<a href="#${i.to}" data-nav="${i.to}">${icon(i.icon)}<span>${esc(i.label)}</span></a>`).join("")}`).join("")}
      </nav>
      <div class="sidebar-foot">
        <div class="user-chip">
          <span class="avatar">${esc(initials(name))}</span>
          <span class="who"><b>${esc(name)}</b><span>${esc(claims.role === "cliente" ? "Cliente" : roleLabel(claims.role))}${claims.region && claims.role === "cliente" ? ` · ${claims.region === "EU" ? "Europa" : "América"}` : ""}</span></span>
          <button class="btn btn-ghost btn-icon" id="logout" aria-label="Terminar sessão" title="Terminar sessão">${icon("logout")}</button>
        </div>
      </div>
    </aside>
    <div class="main">
      <header class="topbar">
        <button class="btn btn-ghost btn-icon menu-btn" id="menu" aria-label="Abrir menu" aria-controls="sidebar">${icon("menu")}</button>
        <span class="crumb" id="crumb"></span>
        <span class="spacer"></span>
        <span class="secure-pill hide-sm" title="Ligação cifrada de ponta a ponta (TLS) e sessão assinada (JWT RS256)">${icon("lock")} Ligação segura</span>
        <button class="btn btn-ghost btn-icon" id="theme" aria-label="Alternar tema claro/escuro" title="Tema">${icon("moon")}</button>
      </header>
      <main class="content" id="view" tabindex="-1"></main>
    </div>
    <nav class="tabbar" style="--tabs:${tabs.length}" aria-label="Navegação rápida">
      ${tabs.map((i) => `<a href="#${i.to}" data-nav="${i.to}">${icon(i.icon)}<span>${esc(i.label.split(" ")[0])}</span></a>`).join("")}
    </nav>
  </div>`;
}

function bindShell() {
  $("#logout")?.addEventListener("click", async () => {
    await logout();
    toast("Sessão terminada com segurança", "info");
    navigate("/login");
  });
  const sidebar = $("#sidebar");
  $("#menu")?.addEventListener("click", () => {
    sidebar.classList.add("open");
    const scrim = document.createElement("div");
    scrim.className = "sidebar-scrim";
    scrim.addEventListener("click", closeMenu);
    document.body.append(scrim);
  });
  $("#theme")?.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    prefs.theme = dark ? "light" : "dark";
    themeIcon();
  });
  themeIcon();
}

function themeIcon() {
  const btn = $("#theme");
  if (!btn) return;
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  btn.innerHTML = icon(dark ? "sun" : "moon");
  btn.setAttribute("aria-label", dark ? "Mudar para tema claro" : "Mudar para tema escuro");
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
    document.title = `${route.title} · Global Scale`;
    await route.view.render({ root: $("#view"), params, navigate });
    return;
  }
  if (!loggedIn) {
    sessionStorage.setItem("gs.next", path);
    return navigate("/login");
  }
  if (!route.roles.includes(claims.role)) return navigate(HOME[claims.role]);

  if (!$(".app") || root.dataset.role !== claims.role) {
    root.innerHTML = shell(claims);
    root.dataset.role = claims.role;
    bindShell();
  }
  closeMenu();
  $$("[data-nav]").forEach((a) => {
    const active = path === a.dataset.nav || (!["/admin", "/ops", "/audit"].includes(a.dataset.nav) && path.startsWith(a.dataset.nav + "/"));
    if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  $("#crumb").textContent = route.title;
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
}

window.addEventListener("hashchange", render);
window.addEventListener("gs:logout", () => {
  toast("A sua sessão expirou. Entre novamente.", "info");
  navigate("/login");
});
document.addEventListener("click", (e) => { if (e.target.closest("[data-reload]")) render(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);

applyTheme();
render();
