// Visão global da instituição (Administrador).
import { api } from "../api.js";
import { barChart } from "../chart.js";
import { money, number } from "../format.js";
import { icon } from "../icons.js";
import { esc } from "../ui.js";
import { bindRowLinks, dailySeries, kpi, transfersTable, users } from "../staff.js";
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
    <div class="grid g-4 keep-2">
      ${kpi("Transferências", String(total), `${done} processadas · ${failed} falhadas`, "transfer")}
      ${kpi("Internacionais", String(intl), `${total ? Math.round((intl / total) * 100) : 0}% do total`, "globe")}
      ${kpi("Clientes", String(clients.length), `${clients.filter((u) => u.status === "PENDENTE_VERIFICACAO").length} a aguardar KYC`, "users")}
      ${kpi("Infraestrutura", `${nodesUp}/${nodesAll}`, status?.all_up ? "todos os nós operacionais" : "serviço degradado", "server")}
    </div>
    <div class="grid g-main" style="margin-top:20px">
      <section class="card"><div class="card-head"><div><h3>Transferências processadas por dia</h3><p class="hint">últimos 14 dias</p></div></div><div id="daily"></div></section>
      <section class="card card-pad"><h3>Saldos sob custódia</h3>
        <dl class="kv" style="margin-top:8px">${Object.entries(o.balances).flatMap(([reg, rows]) => rows.map((b) => `
          <dt>${reg === "EU" ? "Europa" : "América"} · ${esc(b.currency)} <span class="hint">(${b.accounts} contas${Number(b.blocked) ? `, ${b.blocked} bloqueadas` : ""})</span></dt>
          <dd class="num">${esc(money(b.total, b.currency))}</dd>`)).join("")}</dl>
        <h3 style="margin-top:20px">Limites em vigor</h3>
        <dl class="kv" style="margin-top:8px"><dt>Máximo por transferência</dt><dd class="num">${esc(number(o.limits.max_transfer_amount))}</dd>
          <dt>Aprovação obrigatória (operadores) a partir de</dt><dd class="num">${esc(number(o.limits.approval_threshold))}</dd></dl>
        <a class="btn btn-secondary btn-sm" href="#/admin/settings" style="margin-top:14px">${icon("settings")} Configurar limites</a>
      </section>
    </div>
    <div class="grid g-main" style="margin-top:20px">
      <section class="card"><div class="card-head"><h3>Últimas transferências</h3><a class="link" href="#/admin/transfers">Ver todas</a></div>
        <div style="margin-top:8px">${transfersTable(recent.items, dir)}</div></section>
      <section class="card card-pad"><h3>Equipa</h3>
        <dl class="kv" style="margin-top:8px">${["admin", "operador", "auditor"].map((r) => `<dt>${{ admin: "Administradores", operador: "Operadores", auditor: "Auditores" }[r]}</dt>
          <dd class="num">${staff.filter((u) => u.role === r && u.status === "ATIVA").length} ativos</dd>`).join("")}
          <dt>Contas bloqueadas/desativadas</dt><dd class="num">${people.filter((u) => ["BLOQUEADA", "DESATIVADA"].includes(u.status)).length}</dd></dl>
        <a class="btn btn-secondary btn-sm" href="#/admin/users" style="margin-top:14px">${icon("users")} Gerir utilizadores</a>
        <h3 style="margin-top:20px">Últimas 24 h</h3>
        <dl class="kv" style="margin-top:8px"><dt>Transferências</dt><dd class="num">${o.last_24h.n}</dd><dt>Falhadas</dt><dd class="num">${o.last_24h.failed}</dd>
          <dt>Em curso</dt><dd class="num">${o.last_24h.in_progress}</dd></dl>
      </section>
    </div>`;
  barChart(root.querySelector("#daily"), dailySeries(o.daily), { format: (v) => `${v} transferências` });
  bindRowLinks(root, navigate);
}
