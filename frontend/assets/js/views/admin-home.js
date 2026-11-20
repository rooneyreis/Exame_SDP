// Painel do Administrador: o estado da instituição para decidir.
//  [ nós por região: EU · AM · AF (primário/réplica, ativo/em baixo) + serviços (12) ]
//  [ aprovações pendentes (7)                 ] [ limites em vigor (5)                ]
//  [ alertas de transações suspeitas (7)      ] [ transferências por dia + custódia (5)]
import { api } from "../api.js";
import { barChart } from "../chart.js";
import { dateTime, iban, money, number, REGION_CODES, REGIONS, regionName } from "../format.js";
import { icon } from "../icons.js";
import { $, esc } from "../ui.js";
import { dailySeries, users, who } from "../staff.js";
import { pageHead } from "./common.js";

const SERVICE_LABEL = { auth: "Autenticação", coordinator: "Coordenador 2PC", "legacy-bank": "Banco parceiro",
  "api-1": "API · nó 1", "api-2": "API · nó 2" };
const RULE_LABEL = { VALOR_ELEVADO: "Valor elevado", VELOCIDADE: "Frequência anormal", FALHAS_REPETIDAS: "Falhas repetidas",
  LIQUIDACAO_REJEITADA: "Liquidação rejeitada", SEM_APROVACAO: "Sem aprovação", PENDENTE_HA_MUITO: "Pendente há muito",
  FALHA_DE_PROCESSAMENTO: "Recuperação automática" };
const SEV_ORDER = { alta: 0, media: 1, baixa: 2 };

function nodeRow(name, n) {
  const up = n?.up;
  return `<div class="node-row"><span class="status-dot ${up ? "" : "down"}" title="${up ? "ativo" : "em baixo"}"></span>
    <span class="mono">${esc(name)}</span>
    ${up ? `<span class="chip ${n.role === "primário" ? "chip-accent" : ""}">${esc(n.role)}${n.prepared_xacts ? ` · ${n.prepared_xacts} prep.` : ""}</span>`
         : `<span class="chip status-failed">em baixo</span>`}</div>`;
}

export async function render({ root, navigate }) {
  const [status, pending, settings, sus, o, dir] = await Promise.all([
    api("/admin/status").catch(() => null), api("/transfer-requests?status=PENDENTE_APROVACAO&limit=50").catch(() => []),
    api("/admin/settings"), api("/admin/suspicious").catch(() => ({ findings: [], rules: {} })), api("/admin/overview"), users(),
  ]);
  const lim = Object.fromEntries(settings.map((s) => [s.key, s.value]));
  const dbs = status?.databases || {};
  const services = Object.entries(status?.services || {}).filter(([n]) => SERVICE_LABEL[n]);
  const down = [...Object.values(dbs), ...services.map(([, v]) => v)].filter((v) => !v.up).length;
  const alerts = [...sus.findings].sort((a, b) => (SEV_ORDER[a.severity] ?? 3) - (SEV_ORDER[b.severity] ?? 3));
  const high = alerts.filter((f) => f.severity === "alta").length;

  root.innerHTML = `
    ${pageHead("Visão geral", status ? (down ? `${down} componente(s) em baixo · ${pending.length} aprovação(ões) pendente(s)` : `Todos os nós operacionais · ${pending.length} aprovação(ões) pendente(s)`) : "Estado dos nós indisponível",
      `<a class="btn btn-secondary" href="#/admin/infra">${icon("server")} Infraestrutura</a><a class="btn btn-primary" href="#/admin/approvals">${icon("check")} Aprovações${pending.length ? ` · ${pending.length}` : ""}</a>`)}

    <section class="panel">
      <div class="panel-head"><div><h3>Estado dos nós por região</h3><div class="sub">cada região tem um primário e uma réplica em streaming</div></div>
        <span class="chip ${down ? "status-failed" : "status-done"}">${icon(down ? "alert" : "check")}${down ? "serviço degradado" : "operacional"}</span></div>
      <div class="region-nodes">
        ${REGION_CODES.map((r) => {
          const node = REGIONS[r].node;
          const pair = [dbs[node], dbs[`${node}-replica`]];
          const ok = pair.every((n) => n?.up);
          return `<div class="region-col"><header><span class="region-tag">${r}</span><span class="grow"><b>${esc(regionName(r))}</b><br><span>${esc(REGIONS[r].city)} · ${esc(REGIONS[r].currency)}</span></span>
              <span class="status-dot ${ok ? "" : "down"}"></span></header>
            ${nodeRow(node, pair[0])}${nodeRow(`${node}-replica`, pair[1])}</div>`;
        }).join("")}
      </div>
      <div class="svc-strip">
        ${[["pg-core", dbs["pg-core"], "Núcleo (pg-core)"], ...services.map(([n, v]) => [n, v, SERVICE_LABEL[n]]), ["nfs", status?.nfs, "NFS (auditoria)"]]
          .map(([, v, label]) => `<span class="chip"><span class="status-dot ${v?.up ? "" : "down"}" style="width:7px;height:7px"></span>${esc(label)}</span>`).join("")}
      </div>
    </section>

    <div class="bento mt">
      <section class="panel c-7">
        <div class="panel-head"><div><h3>Aprovações pendentes</h3><div class="sub">transferências registadas por operadores acima do limiar</div></div><a class="link-btn" href="#/admin/approvals">Rever todas</a></div>
        <div>${pending.slice(0, 5).map((r) => `
          <a class="queue-item" href="#/admin/approvals" style="color:inherit;text-decoration:none">
            <span class="tx-icon out">${icon("clock")}</span>
            <span class="q-main"><b>${esc(money(r.amount, r.currency))} · ${esc(r.beneficiary_name || iban(r.to_iban))}</b>
              <span>${esc(iban(r.from_iban))} → ${esc(iban(r.to_iban))} · registado por ${esc(who(dir, r.created_by))} · ${esc(dateTime(r.created_at))}</span></span>
            <span class="soft">${icon("arrowRight")}</span></a>`).join("") ||
          `<div class="empty-sm">${icon("check")} Nada para aprovar.</div>`}</div>
      </section>
      <section class="panel c-5">
        <div class="panel-head"><div><h3>Limites em vigor</h3><div class="sub">aplicados pela API e pelo coordenador</div></div><a class="link-btn" href="#/admin/settings">Configurar</a></div>
        <div class="panel-body"><dl class="kv">
          <dt>Máximo por transferência</dt><dd class="num">${esc(number(lim.max_transfer_amount))} EUR</dd>
          <dt>Aprovação a partir de</dt><dd class="num">${esc(number(lim.approval_threshold))}</dd>
          ${lim.daily_limit_eur ? `<dt>Limite diário por cliente</dt><dd class="num">${esc(number(lim.daily_limit_eur))} EUR</dd>` : ""}
          ${lim.max_accounts_per_client ? `<dt>Contas por cliente</dt><dd class="num">até ${esc(number(lim.max_accounts_per_client, 0))}</dd>` : ""}
        </dl></div>
      </section>
    </div>

    <div class="bento">
      <section class="panel c-7">
        <div class="panel-head"><div><h3>Alertas de transações suspeitas</h3><div class="sub">${alerts.length} nos últimos 30 dias · ${high} de severidade alta</div></div><a class="link-btn" href="#/audit/compliance">Conformidade</a></div>
        <div>${alerts.slice(0, 6).map((f) => `
          <div class="finding" ${f.tx_id ? `data-tx="${esc(f.tx_id)}" style="cursor:pointer"` : ""}>
            <span class="sev sev-${esc(f.severity)}" title="severidade ${esc(f.severity)}"></span>
            <div><b>${esc(RULE_LABEL[f.rule] || f.rule)}</b><div class="hint">${esc(f.detail)}</div></div>
            <span class="hint num" style="white-space:nowrap">${esc(dateTime(f.at))}</span></div>`).join("") ||
          `<div class="empty-sm">${icon("check")} Nenhuma regra de fiscalização ativada.</div>`}</div>
      </section>
      <div class="c-5 stack-gap">
        <section class="panel"><div class="panel-head"><div><h3>Transferências por dia</h3><div class="sub">últimos 14 dias</div></div><a class="link-btn" href="#/reports">Relatórios</a></div>
          <div class="panel-body flush" id="daily"></div></section>
        <section class="panel"><div class="panel-head"><h3>Saldos sob custódia</h3></div>
          <div class="panel-body"><dl class="kv">${Object.entries(o.balances).flatMap(([reg, rows]) => rows.map((b) => `
            <dt>${esc(regionName(reg))} · ${esc(b.currency)}</dt><dd class="num">${esc(money(b.total, b.currency))}</dd>`)).join("")}</dl></div></section>
      </div>
    </div>`;
  barChart($("#daily", root), dailySeries(o.daily), { format: (v) => `${v} transferências`, height: 180 });
  root.querySelectorAll("[data-tx]").forEach((el) => el.addEventListener("click", () => navigate(`/tx/${encodeURIComponent(el.dataset.tx)}`)));
}
