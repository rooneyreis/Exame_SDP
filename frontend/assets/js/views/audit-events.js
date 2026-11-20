// Registos de auditoria e segurança (Auditor, Administrador): eventos de todos os nós,
// com responsável, ação, antes/depois, resultado e IP; e o estado da cadeia de hashes.
// Composição: indicadores · filtros · tabela paginada (50) · detalhe em painel lateral.
import { api } from "../api.js";
import { dateTime } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, bindPager, drawer, esc, pagerHtml, paginate } from "../ui.js";
import { downloadCsv, exportButtons, ROLE_LABEL, users, who } from "../staff.js";
import { pageHead } from "./common.js";

const SECURITY = new Set(["ACESSO_NEGADO", "LOGIN_FALHOU", "CONTA_BLOQUEADA", "ADULTERACAO_DETETADA", "PERFIL_ALTERADO",
  "ESTADO_ALTERADO", "LIMITES_ALTERADOS", "DADOS_PESSOAIS_CONSULTADOS", "SIMULACAO_FALHAS"]);
const PAGE = 50;
const today = () => new Date().toISOString().slice(0, 10);
const resultChip = (r) => r ? `<span class="chip ${r === "OK" ? "status-done" : r === "NEGADO" || r === "FALHOU" ? "status-failed" : ""}">${esc(r)}</span>` : `<span class="muted">—</span>`;

export async function render({ root }) {
  const dir = await users();
  const f = { date: today(), action: "", result: "", q: "", security: false, page: 1 };

  root.innerHTML = `
    ${pageHead("Registos de auditoria", "Cada linha está encadeada por SHA-256 à anterior no sistema de ficheiros distribuído: alterar ou apagar um registo quebra a cadeia e é detetado.", exportButtons())}
    <section class="panel" id="kpis"></section>
    <section class="panel mt">
      <div class="filters">
        <input class="input" type="date" id="date" value="${f.date}" aria-label="Dia">
        <div class="search">${icon("search")}<input class="input" id="q" type="search" placeholder="Utilizador, IBAN, referência, IP…" aria-label="Pesquisar"></div>
        <select class="select" id="action" aria-label="Ação"><option value="">Todas as ações</option></select>
        <select class="select" id="result" aria-label="Resultado"><option value="">Todos os resultados</option><option value="OK">Sucesso</option><option value="NEGADO">Negado</option><option value="FALHOU">Falhou</option></select>
        <span class="grow"></span>
        <button class="chip-filter" id="sec" aria-pressed="false">${icon("shield")} Só segurança</button>
      </div>
      <div id="chains" class="row wrap" style="gap:8px;padding:12px 22px;border-bottom:1px solid var(--line)"></div>
      <div id="table"></div>
    </section>`;

  let data = { items: [], chains: {}, actions: [] };
  async function load() {
    const p = new URLSearchParams({ date: f.date, limit: "1000" });
    if (f.action) p.set("action", f.action);
    if (f.result) p.set("result", f.result);
    if (f.q) p.set("q", f.q);
    data = await api(`/admin/audit/events?${p}`);
    f.page = 1;
    $("#action", root).innerHTML = `<option value="">Todas as ações</option>${data.actions.map((a) => `<option ${a === f.action ? "selected" : ""}>${esc(a)}</option>`).join("")}`;
    const chains = Object.entries(data.chains);
    $("#chains", root).innerHTML = chains.length ? `<span class="hint" style="margin-right:4px">Cadeias de hashes:</span>` + chains.map(([file, c]) =>
      `<span class="chip ${c.ok ? "status-done" : "status-failed"}">${icon(c.ok ? "shield" : "alert")}${esc(file)} · ${c.lines}${c.ok ? "" : ` · inválida desde a linha ${c.first_bad_line}`}</span>`).join("")
      : `<span class="hint">Sem registos neste dia.</span>`;
    const items = data.items;
    const intact = chains.every(([, c]) => c.ok);
    $("#kpis", root).innerHTML = `<div class="metric-strip" style="--n:4">
      <div class="metric"><span class="m-label">${icon("doc")} Eventos</span><span class="m-value">${items.length}</span><span class="m-sub">${esc(f.date)}${items.length >= 1000 ? " · limite de 1000" : ""}</span></div>
      <div class="metric"><span class="m-label">${icon("shield")} Eventos de segurança</span><span class="m-value">${items.filter((e) => SECURITY.has(e.event)).length}</span><span class="m-sub">acessos, perfis, limites</span></div>
      <div class="metric"><span class="m-label">${icon("alert")} Negados / falhados</span><span class="m-value">${items.filter((e) => e.result === "NEGADO" || e.result === "FALHOU").length}</span><span class="m-sub">tentativas sem sucesso</span></div>
      <div class="metric"><span class="m-label">${icon("fingerprint")} Integridade</span><span class="m-value" style="color:var(${intact ? "--good-ink" : "--bad-ink"})">${chains.length ? (intact ? "Íntegra" : "Adulterada") : "—"}</span><span class="m-sub">${chains.length} ficheiro(s) verificados</span></div>
    </div>`;
    draw();
  }
  function rows() { return data.items.filter((e) => !f.security || SECURITY.has(e.event)); }
  function draw() {
    const list = rows();
    const pg = paginate(list, f.page, PAGE);
    f.page = pg.page;
    $("#table", root).innerHTML = list.length ? `<div class="table-wrap"><table class="table"><thead><tr><th class="w-date">Data/hora</th><th>Ação</th><th>Responsável</th><th class="hide-sm">Nó</th><th class="hide-sm w-mono">IP</th><th class="w-status">Resultado</th></tr></thead><tbody>
      ${pg.slice.map((e, i) => `<tr class="clickable" data-i="${i}" tabindex="0">
        <td class="w-date num">${esc(dateTime(e.ts))}</td>
        <td><span class="cell-main">${esc(e.event)}</span>${SECURITY.has(e.event) ? ` <span class="hint">· segurança</span>` : ""}${e._tampered ? ` <span class="chip status-failed">${icon("alert")}adulterado</span>` : ""}</td>
        <td><div class="cell-main" style="font-weight:500">${esc(e.actor ? who(dir, e.actor) : e.email || e.operador || "sistema")}</div>${e.actor_role ? `<div class="cell-sub">${esc(ROLE_LABEL[e.actor_role] || e.actor_role)}</div>` : ""}</td>
        <td class="hide-sm mono muted">${esc(e.node)}</td><td class="hide-sm w-mono mono muted">${esc(e.ip || "—")}</td>
        <td class="w-status">${resultChip(e.result)}</td>
      </tr>`).join("")}</tbody></table></div>${pagerHtml(pg, "eventos")}`
      : `<div class="empty"><div class="tx-icon">${icon("search")}</div><h3>Sem eventos</h3><p>Escolha outro dia ou ajuste os filtros.</p></div>`;
    $$("[data-i]", root).forEach((tr) => {
      const open = () => detail(pg.slice[+tr.dataset.i]);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter") open(); });
    });
    bindPager(root, (p) => { f.page = p; draw(); $("#table", root).scrollIntoView({ block: "start", behavior: "smooth" }); });
  }
  function detail(e) {
    const { _file, _line, _tampered, ...entry } = e;
    drawer({
      title: e.event, subtitle: esc(dateTime(e.ts)), wide: !!(e.before || e.after),
      body: `<div style="margin-bottom:6px">${resultChip(e.result)} ${_tampered ? `<span class="chip status-failed">${icon("alert")} cadeia inválida a partir daqui</span>` : `<span class="chip status-done">${icon("shield")} hash verificado</span>`}</div>
        <dl class="kv"><dt>Responsável</dt><dd>${esc(e.actor ? who(dir, e.actor) : e.email || "sistema")}</dd>
        <dt>Perfil</dt><dd>${esc(ROLE_LABEL[e.actor_role] || e.actor_role || "—")}</dd>
        <dt>Nó</dt><dd class="mono">${esc(e.node || "—")}</dd><dt>IP</dt><dd class="mono">${esc(e.ip || "—")}</dd>
        <dt>Registo</dt><dd class="mono">${esc(_file)}:${_line}</dd></dl>
        ${e.before || e.after ? `<div class="section-title">Alteração</div><div class="grid g-2" style="gap:12px"><div><span class="label">Antes</span><div class="event-json">${esc(JSON.stringify(e.before ?? {}, null, 2))}</div></div>
          <div><span class="label">Depois</span><div class="event-json">${esc(JSON.stringify(e.after ?? {}, null, 2))}</div></div></div>` : ""}
        <div class="section-title">Registo completo</div><div class="event-json">${esc(JSON.stringify(entry, null, 2))}</div>`,
      footer: `${e.tx_id ? `<a class="btn btn-secondary" href="#/tx/${encodeURIComponent(e.tx_id)}">${icon("doc")} Ver transferência</a>` : ""}<button class="btn btn-primary" data-close>Fechar</button>`,
    });
  }
  $("#date", root).addEventListener("change", (e) => { f.date = e.target.value; f.action = ""; load(); });
  let t; $("#q", root).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); load(); }, 300); });
  $("#action", root).addEventListener("change", (e) => { f.action = e.target.value; load(); });
  $("#result", root).addEventListener("change", (e) => { f.result = e.target.value; load(); });
  $("#sec", root).addEventListener("click", (e) => { f.security = !f.security; f.page = 1; e.currentTarget.setAttribute("aria-pressed", String(f.security)); draw(); });
  root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv(`auditoria-${f.date}.csv`,
    ["data_hora", "acao", "responsavel", "perfil", "no", "ip", "resultado", "antes", "depois", "hash"],
    rows().map((e) => [e.ts, e.event, e.actor ? who(dir, e.actor) : "", e.actor_role, e.node, e.ip, e.result,
      e.before ? JSON.stringify(e.before) : "", e.after ? JSON.stringify(e.after) : "", e.hash])));
  await load();
}
