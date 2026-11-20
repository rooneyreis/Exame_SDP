// Visão global da instituição (Administrador).
import { api } from "../api.js";
import { barChart } from "../chart.js";
import { money, number, regionName } from "../format.js";
import { icon } from "../icons.js";
import { esc } from "../ui.js";
import { bindRowLinks, dailySeries, transfersTable, users } from "../staff.js";
import { pageHead } from "./common.js";

export async function render({ root, navigate }) {
  const [o, status, recent, dir] = await Promise.all([
    api("/admin/overview"), api("/admin/status").catch(() => null), api("/admin/transfers?limit=8"), users(),
  ]);
  const count = (pred) => o.transactions.filter(pred).reduce((s, r) => s + Number(r.n), 0);
  const total = count(() => true), done = count((r) => r.state === "CONFIRMADA"), failed = count((r) => r.state === "ABORTADA");
  const intl = count((r) => r.kind === "DISTRIBUIDA");
  const people = [...dir.values()];
  const clients = people.filter((u) => u.role === "cliente");
  const staff = people.filter((u) => u.role !== "cliente");
  const nodesUp = status ? Object.values(status.services).filter((v) => v.up).length + Object.values(status.databases).filter((v) => v.up).length : 0;
  const nodesAll = status ? Object.keys(status.services).length + Object.keys(status.databases).length : 0;

  root.innerHTML = `
    ${pageHead("Visão geral", "Atividade da instituição em todas as regiões.",
      `<a class="btn btn-primary" href="#/admin/approvals">${icon("check")} Aprovações${Number(o.pending_approvals.n) ? ` · ${o.pending_approvals.n}` : ""}</a>`)}
    ${Number(o.pending_approvals.n) ? `<a class="banner banner-warn" href="#/admin/approvals" style="margin-bottom:20px;text-decoration:none">${icon("clock")}
      <span><b>${o.pending_approvals.n} transferência(s) registada(s) por operadores aguardam a sua aprovação.</b> Rever agora →</span></a>` : ""}
    <section class="panel"><div class="metric-strip" style="--n:4">
      <div class="metric"><span class="m-label">${icon("transfer")} Transferências</span><span class="m-value">${total}</span><span class="m-sub">${done} processadas · ${failed} falhadas</span></div>
      <div class="metric"><span class="m-label">${icon("globe")} Internacionais (2PC)</span><span class="m-value">${intl}</span><span class="m-sub">${total ? Math.round((intl / total) * 100) : 0}% do total</span></div>
      <div class="metric"><span class="m-label">${icon("users")} Clientes</span><span class="m-value">${clients.length}</span><span class="m-sub">${clients.filter((u) => u.status === "PENDENTE_VERIFICACAO").length} a aguardar KYC</span></div>
      <div class="metric"><span class="m-label">${icon("server")} Infraestrutura</span><span class="m-value" style="color:var(${status?.all_up ? "--good-ink" : "--warn-ink"})">${nodesUp}/${nodesAll}</span><span class="m-sub">${status?.all_up ? "todos os nós operacionais" : "serviço degradado"}</span></div>
    </div></section>
    <div class="bento mt">
      <section class="panel c-8"><div class="panel-head"><div><h3>Transferências processadas por dia</h3><div class="sub">últimos 14 dias</div></div><a class="link-btn" href="#/reports">Relatórios</a></div>
        <div class="panel-body flush" id="daily"></div></section>
      <section class="panel c-4"><div class="panel-head"><h3>Saldos sob custódia</h3></div>
        <div class="panel-body"><dl class="kv">${Object.entries(o.balances).flatMap(([reg, rows]) => rows.map((b) => `
          <dt>${regionName(reg)} · ${esc(b.currency)} <span class="hint">(${b.accounts} contas${Number(b.blocked) ? `, ${b.blocked} bloqueadas` : ""})</span></dt>
          <dd class="num">${esc(money(b.total, b.currency))}</dd>`)).join("")}</dl>
        <div class="section-title">Limites em vigor</div>
        <dl class="kv"><dt>Máximo por transferência</dt><dd class="num">${esc(number(o.limits.max_transfer_amount))}</dd>
          <dt>Aprovação obrigatória a partir de</dt><dd class="num">${esc(number(o.limits.approval_threshold))}</dd></dl></div>
        <div class="panel-foot"><span>Aplicados pela API e pelo coordenador</span><a href="#/admin/settings">Configurar</a></div>
      </section>
    </div>
    <div class="bento">
      <section class="panel c-8"><div class="panel-head"><div><h3>Últimas transferências</h3><div class="sub">clique numa linha para ver responsáveis e integridade</div></div><a class="link-btn" href="#/admin/transfers">Ver todas</a></div>
        <div class="panel-body flush">${transfersTable(recent.items, dir, { showActors: false })}</div></section>
      <div class="c-4 stack-gap">
        <section class="panel"><div class="panel-head"><h3>Últimas 24 horas</h3></div>
          <div class="metric-strip" style="--n:3;border-top:1px solid var(--line)">
            <div class="metric"><span class="m-label">Total</span><span class="m-value">${o.last_24h.n}</span></div>
            <div class="metric"><span class="m-label">Falhadas</span><span class="m-value">${o.last_24h.failed}</span></div>
            <div class="metric"><span class="m-label">Em curso</span><span class="m-value">${o.last_24h.in_progress}</span></div></div></section>
        <section class="panel"><div class="panel-head"><h3>Equipa</h3><a class="link-btn" href="#/admin/users">Gerir</a></div>
          <div class="panel-body"><dl class="kv">${["admin", "operador", "auditor"].map((r) => `<dt>${{ admin: "Administradores", operador: "Operadores", auditor: "Auditores" }[r]}</dt>
            <dd class="num">${staff.filter((u) => u.role === r && u.status === "ATIVA").length} ativos</dd>`).join("")}
            <dt>Contas bloqueadas/desativadas</dt><dd class="num">${people.filter((u) => ["BLOQUEADA", "DESATIVADA"].includes(u.status)).length}</dd></dl></div></section>
      </div>
    </div>`;
  barChart(root.querySelector("#daily"), dailySeries(o.daily), { format: (v) => `${v} transferências` });
  bindRowLinks(root, navigate);
}
