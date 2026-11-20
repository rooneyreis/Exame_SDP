// Utilitários de interface: escape de HTML, toasts, folhas (modais), cópia, estados de carregamento.
import { icon } from "./icons.js";

/** Escapa tudo o que vem da API antes de entrar no HTML (proteção XSS). */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function $(sel, root = document) { return root.querySelector(sel); }
export function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }

export function toast(message, kind = "good") {
  let host = $(".toasts");
  if (!host) {
    host = document.createElement("div");
    host.className = "toasts";
    host.setAttribute("role", "status");
    host.setAttribute("aria-live", "polite");
    document.body.append(host);
  }
  const el = document.createElement("div");
  el.className = "toast";
  const ic = kind === "bad" ? "alert" : kind === "info" ? "info" : "check";
  el.innerHTML = `<span class="t-${kind}">${icon(ic)}</span><span>${esc(message)}</span>`;
  host.append(el);
  setTimeout(() => {
    el.classList.add("leaving");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  }, 3800);
}

/** Folha modal. Devolve { el, close }. Fecha com Esc, clique no fundo ou [data-close]. */
export function sheet({ title, body, footer = "", onClose, labelledBy = "sheet-title" }) {
  const previous = document.activeElement;
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.innerHTML = `
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="${labelledBy}">
      <div class="sheet-head">
        <h2 id="${labelledBy}">${esc(title)}</h2>
        <button class="btn btn-ghost btn-icon" data-close aria-label="Fechar">${icon("x")}</button>
      </div>
      <div class="sheet-body">${body}</div>
      ${footer ? `<div class="sheet-foot">${footer}</div>` : ""}
    </div>`;
  document.body.append(scrim);
  document.body.style.overflow = "hidden";
  let closed = false;
  function close(result) {
    if (closed) return;
    closed = true;
    scrim.classList.add("leaving");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => {
      scrim.remove();
      document.body.style.overflow = "";
      previous?.focus?.();
      onClose?.(result);
    }, 200);
  }
  function onKey(e) { if (e.key === "Escape") close(); }
  document.addEventListener("keydown", onKey);
  scrim.addEventListener("click", (e) => { if (e.target === scrim || e.target.closest("[data-close]")) close(); });
  setTimeout(() => ($("input, select, button:not([data-close])", scrim) || $("[data-close]", scrim))?.focus(), 60);
  return { el: scrim, close };
}

export function confirmSheet({ title, message, confirm = "Confirmar", danger = false }) {
  return new Promise((resolve) => {
    let answered = false;
    const s = sheet({
      title,
      body: `<p class="soft">${message}</p>`,
      footer: `<button class="btn btn-secondary" data-close>Cancelar</button>
               <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-ok>${esc(confirm)}</button>`,
      onClose: () => { if (!answered) resolve(false); },
    });
    $("[data-ok]", s.el).addEventListener("click", () => { answered = true; resolve(true); s.close(); });
  });
}

export async function copy(text, label = "Copiado") {
  try {
    await navigator.clipboard.writeText(text);
    toast(label, "info");
  } catch {
    toast("Não foi possível copiar", "bad");
  }
}

/** Liga os botões [data-copy] dentro de root. */
export function bindCopy(root) {
  $$("[data-copy]", root).forEach((b) =>
    b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); copy(b.dataset.copy, b.dataset.copyLabel || "Copiado para a área de transferência"); }));
}

export function busy(button, on, label) {
  if (!button) return;
  if (on) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span>${label ? `<span>${esc(label)}</span>` : ""}`;
  } else {
    button.disabled = false;
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

export function loading(text = "A carregar…") {
  return `<div class="page-loading"><div class="row"><span class="spinner"></span><span>${esc(text)}</span></div></div>`;
}

export function errorState(err, retry = true) {
  return `<div class="card"><div class="empty">
    <div class="tx-icon failed">${icon("alert")}</div>
    <h3>Não foi possível carregar esta informação</h3>
    <p>${esc(err?.message || err)}</p>
    ${retry ? `<button class="btn btn-secondary" style="margin-top:16px" data-reload>${icon("refresh")} Tentar novamente</button>` : ""}
  </div></div>`;
}

export function statusChip(st) {
  return `<span class="chip status-${st.key}">${icon(st.icon)}${esc(st.label)}</span>`;
}

export function fieldError(input, message) {
  const field = input.closest(".field");
  field?.querySelector(".error-text")?.remove();
  input.removeAttribute("aria-invalid");
  if (message) {
    input.setAttribute("aria-invalid", "true");
    const p = document.createElement("p");
    p.className = "error-text";
    p.innerHTML = `${icon("alert")}<span>${esc(message)}</span>`;
    field?.append(p);
  }
}

/** Painel lateral de detalhe: entra pela direita e sai pelo mesmo caminho. Devolve { el, close }. */
export function drawer({ title, subtitle = "", body, footer = "", wide = false, onClose }) {
  const previous = document.activeElement;
  const scrim = document.createElement("div");
  scrim.className = "drawer-scrim";
  const panel = document.createElement("aside");
  panel.className = `drawer${wide ? " wide" : ""}`;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-labelledby", "drawer-title");
  panel.innerHTML = `
    <div class="drawer-head"><div><h2 id="drawer-title">${esc(title)}</h2>${subtitle ? `<div class="sub">${subtitle}</div>` : ""}</div>
      <button class="btn btn-ghost btn-icon" data-close aria-label="Fechar">${icon("x")}</button></div>
    <div class="drawer-body">${body}</div>
    ${footer ? `<div class="drawer-foot">${footer}</div>` : ""}`;
  document.body.append(scrim, panel);
  let closed = false;
  function close(result) {
    if (closed) return;
    closed = true;
    scrim.classList.add("leaving"); panel.classList.add("leaving");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => { scrim.remove(); panel.remove(); previous?.focus?.(); onClose?.(result); }, 220);
  }
  function onKey(e) { if (e.key === "Escape") close(); }
  document.addEventListener("keydown", onKey);
  scrim.addEventListener("click", () => close());
  panel.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) close(); });
  setTimeout(() => $("[data-close]", panel)?.focus(), 60);
  return { el: panel, close };
}

/** Menu suspenso ancorado a um botão (abre a partir dele). Fecha com Esc ou clique fora. */
export function popover(anchor, html, { className = "", align = "right", onClose } = {}) {
  document.querySelectorAll(".popover").forEach((p) => p._close?.());
  const pop = document.createElement("div");
  pop.className = `popover ${className}`;
  pop.setAttribute("role", "menu");
  pop.innerHTML = html;
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.top = `${r.bottom + 8}px`;
  pop.style.left = `${Math.max(12, Math.min(window.innerWidth - w - 12, align === "right" ? r.right - w : r.left))}px`;
  anchor.setAttribute("aria-expanded", "true");
  function close() {
    pop.remove();
    anchor.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", outside, true);
    document.removeEventListener("keydown", onKey);
    onClose?.();
  }
  function outside(e) { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); }
  function onKey(e) { if (e.key === "Escape") { close(); anchor.focus(); } }
  setTimeout(() => document.addEventListener("mousedown", outside, true));
  document.addEventListener("keydown", onKey);
  pop._close = close;
  return { el: pop, close };
}

/** Paginação no cliente. */
export function paginate(items, page, size) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(Math.max(1, page), pages);
  return { page: p, pages, slice: items.slice((p - 1) * size, p * size), from: items.length ? (p - 1) * size + 1 : 0, to: Math.min(p * size, items.length), total: items.length };
}

export function pagerHtml({ page, pages, from, to, total }, label = "registos") {
  const nums = [];
  for (let i = 1; i <= pages; i++) if (i === 1 || i === pages || Math.abs(i - page) <= 1) nums.push(i); else if (nums[nums.length - 1] !== "…") nums.push("…");
  return `<div class="pagination"><span>${total ? `${from}–${to} de ${total} ${label}` : `0 ${label}`}</span>
    <div class="pages"><button data-page="${page - 1}" ${page <= 1 ? "disabled" : ""} aria-label="Anterior">${icon("chevronLeft")}</button>
    ${nums.map((n) => n === "…" ? `<span class="muted">…</span>` : `<button data-page="${n}" ${n === page ? 'aria-current="true"' : ""}>${n}</button>`).join("")}
    <button data-page="${page + 1}" ${page >= pages ? "disabled" : ""} aria-label="Seguinte">${icon("chevronRight")}</button></div></div>`;
}

export function bindPager(root, onPage) {
  root.querySelectorAll(".pagination [data-page]").forEach((b) => b.addEventListener("click", () => onPage(Number(b.dataset.page))));
}
