// Utilizadores e perfis (Administrador): criar, editar, mudar perfil, bloquear, desbloquear,
// desativar — tudo validado no backend (incl. "ninguém altera o próprio perfil").
import { api } from "../api.js";
import { dateTime, initials } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, confirmSheet, drawer, esc, fieldError, sheet, toast } from "../ui.js";
import { roleBadge, ROLE_LABEL, userStatusChip, users } from "../staff.js";
import { pageHead } from "./common.js";

export async function render({ root, claims }) {
  let tab = "staff", q = "", role = "", statusF = "";

  async function draw() {
    const list = [...(await users({ fresh: true })).values()];
    const rows = list.filter((u) => (tab === "staff" ? u.role !== "cliente" : u.role === "cliente") &&
      (!role || u.role === role) && (!statusF || u.status === statusF) &&
      (!q || [u.full_name, u.email, u.phone].some((v) => (v || "").toLowerCase().includes(q.toLowerCase()))));
    root.innerHTML = `
      ${pageHead("Utilizadores e perfis", "Gestão de acessos. As permissões de cada perfil são aplicadas no servidor em cada pedido.",
        `<button class="btn btn-secondary" id="matrix">${icon("shield")} Perfis e permissões</button><button class="btn btn-primary" id="new">${icon("plus")} Novo utilizador</button>`)}
      <section class="panel"><div class="metric-strip" style="--n:4">
        <div class="metric"><span class="m-label">${icon("users")} Equipa</span><span class="m-value">${list.filter((u) => u.role !== "cliente").length}</span><span class="m-sub">${["admin", "operador", "auditor"].map((r) => `${list.filter((u) => u.role === r).length} ${ROLE_LABEL[r].toLowerCase()}`).join(" · ")}</span></div>
        <div class="metric"><span class="m-label">${icon("user")} Clientes</span><span class="m-value">${list.filter((u) => u.role === "cliente").length}</span><span class="m-sub">${list.filter((u) => u.role === "cliente" && u.status === "ATIVA").length} ativos</span></div>
        <div class="metric"><span class="m-label">${icon("clock")} A aguardar KYC</span><span class="m-value">${list.filter((u) => u.status === "PENDENTE_VERIFICACAO").length}</span><span class="m-sub"><a href="#/ops/kyc">abrir verificação</a></span></div>
        <div class="metric"><span class="m-label">${icon("lock")} Bloqueados / desativados</span><span class="m-value">${list.filter((u) => u.status === "BLOQUEADA" || u.status === "DESATIVADA").length}</span><span class="m-sub">${list.filter((u) => u.locked_until && new Date(u.locked_until) > new Date()).length} com bloqueio temporário</span></div>
      </div></section>
      <section class="panel mt">
        <div class="filters">
          <div class="segmented" role="group"><button data-tab="staff" aria-pressed="${tab === "staff"}">Equipa</button><button data-tab="clients" aria-pressed="${tab === "clients"}">Clientes</button></div>
          <div class="search">${icon("search")}<input class="input" id="q" type="search" value="${esc(q)}" placeholder="Nome, email ou telefone"></div>
          ${tab === "staff" ? `<select class="select" id="role"><option value="">Todos os perfis</option>${["admin", "operador", "auditor"].map((r) => `<option value="${r}" ${r === role ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}</select>` : ""}
          <select class="select" id="st"><option value="">Todos os estados</option>${["ATIVA", "BLOQUEADA", "DESATIVADA", "PENDENTE_VERIFICACAO"].map((s) => `<option value="${s}" ${s === statusF ? "selected" : ""}>${s === "PENDENTE_VERIFICACAO" ? "Pendente" : s.charAt(0) + s.slice(1).toLowerCase()}</option>`).join("")}</select>
        </div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Utilizador</th><th class="hide-sm">Contacto</th><th class="w-status">Perfil</th><th class="w-status">Estado</th><th class="hide-sm w-date">Criado</th><th class="w-actions"></th></tr></thead><tbody>
          ${rows.map((u) => `<tr>
            <td><div class="row"><span class="avatar">${esc(initials(u.full_name))}</span><div><b style="font-weight:560">${esc(u.full_name)}</b>${u.id === claims.sub ? ` <span class="hint">(você)</span>` : ""}
              ${u.locked_until && new Date(u.locked_until) > new Date() ? `<div class="hint" style="color:var(--warn-ink)">bloqueio temporário por tentativas falhadas</div>` : ""}</div></div></td>
            <td class="hide-sm">${esc(u.email)}<div class="hint">${esc(u.phone)}</div></td>
            <td>${roleBadge(u.role)}</td><td>${userStatusChip(u.status)}</td>
            <td class="hide-sm">${esc(dateTime(u.created_at))}</td>
            <td class="r"><button class="btn btn-secondary btn-sm" data-user="${esc(u.id)}">${icon("settings")} Gerir</button></td></tr>`).join("") || `<tr><td colspan="6"><div class="empty">Sem resultados.</div></td></tr>`}
        </tbody></table></div>
      </section>`;
    $$("[data-tab]", root).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; role = ""; draw(); }));
    let t; $("#q", root).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { q = e.target.value; draw(); }, 250); });
    $("#role", root)?.addEventListener("change", (e) => { role = e.target.value; draw(); });
    $("#st", root).addEventListener("change", (e) => { statusF = e.target.value; draw(); });
    $$("[data-user]", root).forEach((b) => b.addEventListener("click", () => manage(list.find((u) => u.id === b.dataset.user))));
    $("#new", root).addEventListener("click", create);
    $("#matrix", root).addEventListener("click", showMatrix);
  }

  function manage(u) {
    const self = u.id === claims.sub;
    const staff = u.role !== "cliente";
    const actions = [];
    if (u.status === "ATIVA") actions.push(["block", "Bloquear", "lock"]);
    if (u.status === "BLOQUEADA" || (u.status === "ATIVA" && u.locked_until)) actions.push(["unblock", "Desbloquear", "key"]);
    if (u.status !== "DESATIVADA") actions.push(["deactivate", "Desativar", "x"]);
    if (u.status === "DESATIVADA") actions.push(["reactivate", "Reativar", "refresh"]);
    const s = drawer({
      title: "Gerir utilizador", subtitle: esc(u.email),
      body: `
        <div class="row" style="gap:14px;margin-bottom:16px"><span class="avatar" style="width:48px;height:48px">${esc(initials(u.full_name))}</span>
          <div><h3>${esc(u.full_name)}</h3><div class="row" style="gap:8px;margin-top:4px">${roleBadge(u.role)}${userStatusChip(u.status)}</div></div></div>
        <div class="stack" style="gap:12px">
          <div class="field"><label for="u-name">Nome</label><input class="input" id="u-name" value="${esc(u.full_name)}"></div>
          <div class="grid g-2" style="gap:12px"><div class="field"><label for="u-email">Email</label><input class="input" id="u-email" value="${esc(u.email)}"></div>
            <div class="field"><label for="u-phone">Telefone</label><input class="input" id="u-phone" value="${esc(u.phone)}"></div></div>
          ${staff ? `<div class="field"><label for="u-role">Perfil</label><select class="select" id="u-role" ${self ? "disabled" : ""}>${["operador", "auditor", "admin"].map((r) => `<option value="${r}" ${r === u.role ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}</select>
            <p class="hint">${self ? "Não pode alterar o seu próprio perfil." : "Mudar o perfil termina as sessões ativas deste utilizador."}</p></div>`
            : `<p class="hint">${icon("info")} O perfil de um cliente não pode ser convertido em perfil de equipa.</p>`}
          <div id="u-err"></div>
        </div>
        ${self ? "" : `<div style="margin-top:18px;padding-top:16px;border-top:1px solid var(--line)"><span class="label">Estado da conta</span>
          <div class="row wrap" style="gap:8px;margin-top:8px">${actions.map(([a, l, i]) => `<button class="btn btn-secondary btn-sm" data-action="${a}">${icon(i)} ${l}</button>`).join("")}</div></div>`}`,
      footer: `<button class="btn btn-secondary" data-close>Fechar</button><button class="btn btn-primary" id="save">Guardar</button>`,
    });
    $("#save", s.el).addEventListener("click", async (e) => {
      const body = {};
      const name = $("#u-name", s.el).value.trim(), email = $("#u-email", s.el).value.trim().toLowerCase(), phone = $("#u-phone", s.el).value.replace(/\s/g, "");
      if (name !== u.full_name) body.full_name = name;
      if (email !== u.email) body.email = email;
      if (phone !== u.phone) body.phone = phone;
      const r = $("#u-role", s.el);
      if (r && !r.disabled && r.value !== u.role) body.role = r.value;
      if (!Object.keys(body).length) return s.close();
      busy(e.currentTarget, true);
      try {
        await api(`/admin/users/${u.id}`, { method: "PATCH", body });
        toast(body.role ? `Perfil alterado para ${ROLE_LABEL[body.role]}` : "Utilizador atualizado");
        s.close(); draw();
      } catch (ex) {
        busy(e.currentTarget, false);
        $("#u-err", s.el).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
      }
    });
    $$("[data-action]", s.el).forEach((b) => b.addEventListener("click", async () => {
      const labels = { block: "bloquear", unblock: "desbloquear", deactivate: "desativar", reactivate: "reativar" };
      const ok = await confirmSheet({ title: `${labels[b.dataset.action][0].toUpperCase()}${labels[b.dataset.action].slice(1)} utilizador`,
        message: `Confirma ${labels[b.dataset.action]} a conta de <b>${esc(u.full_name)}</b>? ${["block", "deactivate"].includes(b.dataset.action) ? "As sessões ativas são terminadas." : ""} A ação fica registada na auditoria.`,
        confirm: "Confirmar", danger: ["block", "deactivate"].includes(b.dataset.action) });
      if (!ok) return;
      try {
        await api(`/admin/users/${u.id}/status`, { method: "POST", body: { action: b.dataset.action } });
        toast("Estado atualizado");
        s.close(); draw();
      } catch (ex) { toast(ex.message, "bad"); }
    }));
  }

  function create() {
    const s = drawer({
      title: "Novo utilizador da equipa", subtitle: "O acesso fica ativo de imediato e é registado na auditoria.",
      body: `<div class="stack" style="gap:12px">
        <div class="field"><label for="n-name">Nome completo</label><input class="input" id="n-name"></div>
        <div class="grid g-2" style="gap:12px"><div class="field"><label for="n-email">Email</label><input class="input" id="n-email" type="email"></div>
          <div class="field"><label for="n-phone">Telefone</label><input class="input" id="n-phone" type="tel"></div></div>
        <div class="field"><label for="n-role">Perfil</label><select class="select" id="n-role"><option value="operador">Operador</option><option value="auditor">Auditor</option><option value="admin">Administrador</option></select></div>
        <div class="field"><label for="n-pw">Palavra-passe inicial</label><input class="input" id="n-pw" type="password" autocomplete="new-password"><p class="hint">8+ caracteres, maiúscula, número e símbolo.</p></div>
        <div id="n-err"></div></div>`,
      footer: `<button class="btn btn-secondary" data-close>Cancelar</button><button class="btn btn-primary" id="create">${icon("plus")} Criar acesso</button>`,
    });
    $("#create", s.el).addEventListener("click", async (e) => {
      const v = (id) => $(`#${id}`, s.el).value.trim();
      if (v("n-name").length < 3) return fieldError($("#n-name", s.el), "Indique o nome");
      busy(e.currentTarget, true);
      try {
        await api("/admin/staff", { method: "POST", body: { full_name: v("n-name"), email: v("n-email"), phone: v("n-phone").replace(/\s/g, ""), role: v("n-role"), password: $("#n-pw", s.el).value } });
        toast("Utilizador criado");
        s.close(); tab = "staff"; draw();
      } catch (ex) {
        busy(e.currentTarget, false);
        $("#n-err", s.el).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.status === 409 ? "Já existe um utilizador com este email ou telefone." : ex.message)}</span></div>`;
      }
    });
  }

  async function showMatrix() {
    const m = await api("/admin/roles");
    const roles = ["cliente", "operador", "auditor", "admin"];
    sheet({
      title: "Perfis e permissões",
      body: `<p class="hint" style="margin-bottom:12px">Fonte única: <span class="mono">common/rbac.py</span>. O backend verifica a permissão em cada pedido — esconder um botão nunca é a única proteção.</p>
        <div class="table-wrap"><table class="perm-grid"><thead><tr><th>Permissão</th>${roles.map((r) => `<th>${ROLE_LABEL[r]}</th>`).join("")}</tr></thead><tbody>
        ${Object.entries(m.permissions).filter(([p]) => !p.includes("internal")).map(([p, d]) => `<tr><td>${esc(d)}<div class="hint mono">${esc(p)}</div></td>
          ${roles.map((r) => `<td>${m.roles[r]?.includes(p) ? `<span class="yes">${icon("check")}</span>` : `<span class="no">—</span>`}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>`,
    }).el.querySelector(".sheet").style.width = "min(860px, 100%)";
  }

  await draw();
}
