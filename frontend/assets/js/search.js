// Pesquisa global (Ctrl/Cmd+K): páginas, contas por IBAN, transferências por referência,
// beneficiários e (para quem tem permissão) utilizadores e contas de toda a instituição.
import { api, session } from "./api.js";
import { iban as fmtIban, money, IBAN_RE, IBAN_PARTIAL_RE } from "./format.js";
import { icon } from "./icons.js";
import { beneficiaries } from "./store.js";
import { esc } from "./ui.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let dataCache = { sub: null, at: 0, accounts: [], users: [] };

async function loadData(role) {
  const sub = session.claims?.sub;
  if (dataCache.sub === sub && Date.now() - dataCache.at < 120_000) return dataCache;
  const d = { sub, at: Date.now(), accounts: [], users: [] };
  try {
    if (role === "cliente") { d.accounts = await api("/accounts"); await beneficiaries.load().catch(() => []); }
    if (role === "admin" || role === "auditor") d.accounts = await api("/admin/accounts");
    if (role !== "cliente") d.users = await api("/admin/users");
  } catch { /* pesquisa funciona com o que houver */ }
  dataCache = d;
  return d;
}

export function openSearch({ navigate, nav, role }) {
  if (document.querySelector(".palette-scrim")) return;
  const previous = document.activeElement;
  const scrim = document.createElement("div");
  scrim.className = "palette-scrim";
  scrim.innerHTML = `<div class="palette" role="dialog" aria-modal="true" aria-label="Pesquisa global">
      <div class="palette-input">${icon("search")}<input id="pq" placeholder="Pesquisar páginas, IBAN, referências${role !== "cliente" ? ", clientes" : ", beneficiários"}…" autocomplete="off" spellcheck="false"><span class="kbd">Esc</span></div>
      <div class="palette-results" id="pr" role="listbox"></div>
      <div class="palette-foot"><span><span class="kbd">↑</span> <span class="kbd">↓</span> navegar</span><span><span class="kbd">Enter</span> abrir</span><span><span class="kbd">Ctrl</span> <span class="kbd">K</span> pesquisa</span></div>
    </div>`;
  document.body.append(scrim);
  const input = scrim.querySelector("#pq"), results = scrim.querySelector("#pr");
  let items = [], active = 0, data = dataCache;
  loadData(role).then((d) => { data = d; render(); });

  function close() { scrim.remove(); document.removeEventListener("keydown", onKey, true); previous?.focus?.(); }
  function go(item) { close(); navigate(item.to); }

  function build(q) {
    const s = q.trim().toLowerCase();
    const groups = [];
    const pages = nav.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })))
      .filter((i) => !s || i.label.toLowerCase().includes(s) || i.group.toLowerCase().includes(s))
      .map((i) => ({ icon: i.icon, title: i.label, sub: i.group, to: i.to }));
    const ibanQ = q.trim().toUpperCase().replace(/\s/g, "").replace(IBAN_PARTIAL_RE, "GS-$1-$2");
    if (IBAN_RE.test(ibanQ)) groups.push(["Conta", [{ icon: "wallet", title: `Abrir conta ${fmtIban(ibanQ)}`, sub: "Detalhe e extrato", to: `/accounts/${ibanQ}` }]]);
    if (UUID.test(q.trim())) groups.push(["Transferência", [{ icon: "doc", title: "Abrir comprovativo", sub: q.trim(), to: `/tx/${q.trim()}` }]]);
    if (s.length >= 2) {
      const accs = data.accounts.filter((a) => a.iban.toLowerCase().includes(s.replace(/\s/g, "")) ||
        (data.users.find((u) => u.id === a.user_id)?.full_name || "").toLowerCase().includes(s)).slice(0, 6)
        .map((a) => ({ icon: "wallet", title: fmtIban(a.iban), sub: `${data.users.find((u) => u.id === a.user_id)?.full_name || "Conta"} · ${money(a.balance, a.currency)}`, to: `/accounts/${a.iban}` }));
      if (accs.length) groups.push(["Contas", accs]);
      if (role === "cliente") {
        const bens = beneficiaries.all().filter((b) => b.name.toLowerCase().includes(s) || b.iban.toLowerCase().includes(s)).slice(0, 6)
          .map((b) => ({ icon: "user", title: b.name, sub: `Transferir para ${fmtIban(b.iban)}`, to: `/transfer?to=${encodeURIComponent(b.iban)}&name=${encodeURIComponent(b.name)}` }));
        if (bens.length) groups.push(["Beneficiários", bens]);
      } else {
        const users = data.users.filter((u) => [u.full_name, u.email, u.phone].some((v) => (v || "").toLowerCase().includes(s))).slice(0, 6)
          .map((u) => ({ icon: "user", title: u.full_name, sub: `${u.email} · ${u.role}`, to: role === "admin" ? `/admin/users?q=${encodeURIComponent(u.email)}` : "/ops/accounts" }));
        if (users.length) groups.push(["Pessoas", users]);
      }
    }
    if (pages.length) groups.push(["Páginas", pages.slice(0, s ? 8 : 12)]);
    return groups;
  }

  function render() {
    const groups = build(input.value);
    items = groups.flatMap(([, list]) => list);
    active = Math.min(active, Math.max(items.length - 1, 0));
    let k = 0;
    results.innerHTML = items.length ? groups.map(([g, list]) => `<div class="palette-group">${esc(g)}</div>${list.map((it) => {
      const i = k++;
      return `<div class="palette-item ${i === active ? "active" : ""}" role="option" data-i="${i}" aria-selected="${i === active}">
        <span class="pi-ic">${icon(it.icon)}</span><span style="min-width:0"><b style="font-weight:560">${esc(it.title)}</b><span class="pi-sub">${esc(it.sub)}</span></span></div>`;
    }).join("")}`).join("") : `<div class="empty-sm">Sem resultados para “${esc(input.value)}”.</div>`;
    results.querySelectorAll("[data-i]").forEach((el) => {
      el.addEventListener("mousemove", () => { if (active !== +el.dataset.i) { active = +el.dataset.i; highlight(); } });
      el.addEventListener("click", () => go(items[+el.dataset.i]));
    });
  }
  function highlight() {
    results.querySelectorAll("[data-i]").forEach((el) => {
      const on = +el.dataset.i === active;
      el.classList.toggle("active", on); el.setAttribute("aria-selected", String(on));
      if (on) el.scrollIntoView({ block: "nearest" });
    });
  }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, items.length - 1); highlight(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); highlight(); }
    else if (e.key === "Enter" && items[active]) { e.preventDefault(); go(items[active]); }
  }
  input.addEventListener("input", () => { active = 0; render(); });
  document.addEventListener("keydown", onKey, true);
  scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
  render();
  setTimeout(() => input.focus(), 30);
}
