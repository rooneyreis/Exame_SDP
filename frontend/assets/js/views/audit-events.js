// Registos de auditoria e segurança (Auditor, Administrador): eventos de todos os nós,
// com responsável, ação, antes/depois, resultado e IP; e o estado da cadeia de hashes.
import { api } from "../api.js";
import { dateTime } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, esc, sheet } from "../ui.js";
import { downloadCsv, exportButtons, ROLE_LABEL, users, who } from "../staff.js";
import { pageHead } from "./common.js";

const SECURITY = new Set(["ACESSO_NEGADO", "LOGIN_FALHOU", "CONTA_BLOQUEADA", "ADULTERACAO_DETETADA", "PERFIL_ALTERADO",
  "ESTADO_ALTERADO", "LIMITES_ALTERADOS", "DADOS_PESSOAIS_CONSULTADOS", "SIMULACAO_FALHAS"]);
const today = () => new Date().toISOString().slice(0, 10);

export async function render({ root }) {
  const dir = await users();
  const f = { date: today(), action: "", result: "", q: "", security: false };

  root.innerHTML = `
    ${pageHead("Registos de auditoria e segurança", "Cada linha está encadeada por SHA-256 à anterior no sistema de ficheiros distribuído: alterar ou apagar um registo quebra a cadeia e é detetado.", exportButtons())}
    <div id="chains" class="row wrap" style="gap:8px;margin-bottom:16px"></div>
    <div class="card">
      <div class="toolbar">
        <input class="input" type="date" id="date" value="${f.date}" style="width:auto">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Utilizador, IBAN, referência, IP…"></div>
        <select class="select" id="action" style="width:auto"><option value="">Todas as ações</option></select>
        <select class="select" id="result" style="width:auto"><option value="">Todos os resultados</option><option value="OK">Sucesso</option><option value="NEGADO">Negado</option><option value="FALHOU">Falhou</option></select>
        <label class="row" style="gap:8px;font-size:.86rem"><input type="checkbox" id="sec" style="width:17px;height:17px;accent-color:var(--accent)"> Só segurança</label>
      </div>
      <div id="table"></div>
      <div class="pager"><span class="hint" id="count"></span></div>
    </div>`;

  let data = { items: [] };
  async function load() {
    const p = new URLSearchParams({ date: f.date, limit: "1000" });
    if (f.action) p.set("action", f.action);
    if (f.result) p.set("result", f.result);
    if (f.q) p.set("q", f.q);
    data = await api(`/admin/audit/events?${p}`);
    const sel = $("#action", root);
    sel.innerHTML = `<option value="">Todas as ações</option>${data.actions.map((a) => `<option ${a === f.action ? "selected" : ""}>${esc(a)}</option>`).join("")}`;
    $("#chains", root).innerHTML = Object.entries(data.chains).map(([file, c]) =>
      `<span class="chip ${c.ok ? "status-done" : "status-failed"}">${icon(c.ok ? "shield" : "alert")}${esc(file)} · ${c.lines}${c.ok ? "" : ` · inválida desde a linha ${c.first_bad_line}`}</span>`).join("")
      || `<span class="hint">Sem registos neste dia.</span>`;
    draw();
  }
  function rows() { return data.items.filter((e) => !f.security || SECURITY.has(e.event)); }
  function draw() {
    const list = rows();
    $("#table", root).innerHTML = list.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Data/hora</th><th>Ação</th><th>Responsável</th><th class="hide-sm">Nó</th><th class="hide-sm">IP</th><th>Resultado</th></tr></thead><tbody>
      ${list.map((e, i) => `<tr class="clickable" data-i="${i}">
        <td class="num" style="white-space:nowrap">${esc(dateTime(e.ts))}</td>
        <td><b style="font-weight:560">${esc(e.event)}</b>${e._tampered ? ` <span class="chip status-failed">${icon("alert")}adulterado</span>` : ""}</td>
        <td>${esc(e.actor ? who(dir, e.actor) : e.email || e.operador || "sistema")}${e.actor_role ? `<div class="hint">${esc(ROLE_LABEL[e.actor_role] || e.actor_role)}</div>` : ""}</td>
        <td class="hide-sm mono">${esc(e.node)}</td><td class="hide-sm mono">${esc(e.ip || "—")}</td>
        <td>${e.result ? `<span class="chip ${e.result === "OK" ? "status-done" : e.result === "NEGADO" || e.result === "FALHOU" ? "status-failed" : ""}">${esc(e.result)}</span>` : "—"}</td>
      </tr>`).join("")}</tbody></table></div>`
      : `<div class="empty"><div class="tx-icon">${icon("search")}</div><h3>Sem eventos</h3></div>`;
    $("#count", root).textContent = `${list.length} evento(s)`;
    $$("[data-i]", root).forEach((tr) => tr.addEventListener("click", () => detail(list[tr.dataset.i])));
  }
  function detail(e) {
    const { _file, _line, _tampered, ...entry } = e;
    sheet({
      title: e.event,
      body: `<dl class="kv"><dt>Data/hora</dt><dd>${esc(dateTime(e.ts))}</dd>
        <dt>Responsável</dt><dd>${esc(e.actor ? who(dir, e.actor) : "—")}</dd><dt>IP</dt><dd class="mono">${esc(e.ip || "—")}</dd>
        <dt>Resultado</dt><dd>${esc(e.result || "—")}</dd><dt>Registo</dt><dd class="mono">${esc(_file)}:${_line}</dd>
        <dt>Integridade</dt><dd>${_tampered ? "cadeia inválida a partir daqui" : "hash verificado"}</dd></dl>
        ${e.before || e.after ? `<div class="grid g-2" style="margin-top:14px;gap:12px"><div><span class="label">Antes</span><div class="event-json">${esc(JSON.stringify(e.before ?? {}, null, 2))}</div></div>
          <div><span class="label">Depois</span><div class="event-json">${esc(JSON.stringify(e.after ?? {}, null, 2))}</div></div></div>` : ""}
        <span class="label" style="display:block;margin-top:14px">Registo completo</span><div class="event-json">${esc(JSON.stringify(entry, null, 2))}</div>`,
    });
  }
  $("#date", root).addEventListener("change", (e) => { f.date = e.target.value; f.action = ""; load(); });
  let t; $("#q", root).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); load(); }, 300); });
  $("#action", root).addEventListener("change", (e) => { f.action = e.target.value; load(); });
  $("#result", root).addEventListener("change", (e) => { f.result = e.target.value; load(); });
  $("#sec", root).addEventListener("change", (e) => { f.security = e.target.checked; draw(); });
  root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv(`auditoria-${f.date}.csv`,
    ["data_hora", "acao", "responsavel", "perfil", "no", "ip", "resultado", "antes", "depois", "hash"],
    rows().map((e) => [e.ts, e.event, e.actor ? who(dir, e.actor) : "", e.actor_role, e.node, e.ip, e.result,
      e.before ? JSON.stringify(e.before) : "", e.after ? JSON.stringify(e.after) : "", e.hash])));
  await load();
}
