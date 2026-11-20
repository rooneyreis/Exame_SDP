// Pedidos de transferência registados por operadores.
//  Administrador: aprova ou rejeita (o backend impede quem registou de aprovar).
//  Operador: acompanha os seus pedidos (pendentes, concluídos, rejeitados).
//  Auditor: consulta, só leitura.
import { api } from "../api.js";
import { dateTime, iban, money } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, drawer, esc, fieldError, toast } from "../ui.js";
import { downloadCsv, exportButtons, REQUEST_STATUS, requestChip, users, who } from "../staff.js";
import { pageHead } from "./common.js";

const TABS = [["PENDENTE_APROVACAO", "Pendentes"], ["EM_EXECUCAO", "Em processamento"], ["EXECUTADA", "Concluídas"],
  ["REJEITADA", "Rejeitadas"], ["FALHADA", "Falhadas"], ["", "Todas"]];

export async function render({ root, claims, navigate }) {
  const canDecide = claims.role === "admin";
  const isOperator = claims.role === "operador";
  let tab = canDecide ? "PENDENTE_APROVACAO" : "";
  let mine = isOperator;
  const dir = await users();

  async function draw() {
    const params = new URLSearchParams({ limit: "300" });
    if (tab) params.set("status", tab);
    if (mine) params.set("mine", "true");
    const rows = await api(`/transfer-requests?${params}`);
    const title = canDecide ? "Aprovações" : isOperator ? "Operações" : "Pedidos de transferência";
    const sub = canDecide ? "Transferências registadas por operadores acima do limiar de aprovação. Quem regista um pedido nunca o pode aprovar."
      : isOperator ? "Transferências que registou: pendentes de aprovação, concluídas, rejeitadas e falhadas." : "Registo completo de pedidos, decisões e responsáveis (só leitura).";
    root.innerHTML = `
      ${pageHead(title, sub, `${isOperator ? `<a class="btn btn-primary" href="#/ops/transfer">${icon("plus")} Nova transferência</a>` : ""}${exportButtons()}`)}
      <section class="panel">
        <div class="filters">
          <div class="segmented" role="group" aria-label="Estado">${TABS.map(([k, l]) => `<button data-tab="${k}" aria-pressed="${k === tab}">${l}</button>`).join("")}</div>
          ${isOperator ? `<label class="row" style="gap:8px;font-size:.86rem"><input type="checkbox" id="mine" ${mine ? "checked" : ""} style="width:17px;height:17px;accent-color:var(--accent)"> Só os meus</label>` : ""}
          <span class="hint" style="margin-left:auto">${rows.length} pedido(s)</span>
        </div>
        ${rows.length ? `<div class="table-wrap"><table class="table"><thead><tr>
            <th class="w-date">Registado</th><th>Origem → Destino</th><th class="w-money">Montante</th><th class="hide-sm">Registado por</th><th class="hide-sm">Decisão</th><th>Estado</th>${canDecide ? "<th></th>" : ""}</tr></thead><tbody>
          ${rows.map((r) => `<tr class="clickable" data-req="${esc(r.id)}">
            <td class="num" style="white-space:nowrap">${esc(dateTime(r.created_at))}</td>
            <td><span class="mono">${esc(iban(r.from_iban))}</span><br><span class="mono muted">→ ${esc(iban(r.to_iban))}</span>${r.beneficiary_name ? `<div class="hint">${esc(r.beneficiary_name)}</div>` : ""}</td>
            <td class="w-money"><span class="amount num">${esc(money(r.amount, r.currency))}</span>${r.requires_approval ? `<div class="hint">exige aprovação</div>` : ""}</td>
            <td class="hide-sm">${esc(who(dir, r.created_by))}</td>
            <td class="hide-sm">${r.decided_by ? `${esc(who(dir, r.decided_by))}<div class="hint">${esc(dateTime(r.decided_at))}</div>` : `<span class="muted">—</span>`}</td>
            <td>${requestChip(r.effective_status)}</td>
            ${canDecide ? `<td class="r">${r.effective_status === "PENDENTE_APROVACAO" ? `<button class="btn btn-primary btn-sm" data-open="${esc(r.id)}">Rever</button>` : ""}</td>` : ""}
          </tr>`).join("")}</tbody></table></div>`
        : `<div class="empty"><div class="tx-icon in">${icon("check")}</div><h3>Sem pedidos neste estado</h3></div>`}
      </section>`;
    $$("[data-tab]", root).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; draw(); }));
    $("#mine", root)?.addEventListener("change", (e) => { mine = e.target.checked; draw(); });
    $$("[data-req]", root).forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("button")) detail(tr.dataset.req); }));
    $$("[data-open]", root).forEach((b) => b.addEventListener("click", () => detail(b.dataset.open)));
    root.querySelector('[data-export="csv"]').addEventListener("click", () => downloadCsv(`pedidos-${new Date().toISOString().slice(0, 10)}.csv`,
      ["registado", "origem", "destino", "beneficiario", "montante", "moeda", "registado_por", "decidido_por", "decidido_em", "motivo", "estado", "tx_id"],
      rows.map((r) => [r.created_at, r.from_iban, r.to_iban, r.beneficiary_name, r.amount, r.currency, who(dir, r.created_by),
        who(dir, r.decided_by), r.decided_at, r.decision_reason, REQUEST_STATUS[r.effective_status]?.label, r.tx_id])));
    root.querySelector('[data-export="pdf"]').addEventListener("click", () => window.print());
  }

  async function detail(id) {
    const r = await api(`/transfer-requests/${id}`);
    const pending = r.effective_status === "PENDENTE_APROVACAO";
    const ownRequest = r.created_by === claims.sub;
    const s = drawer({
      title: pending && canDecide ? "Rever pedido de transferência" : "Pedido de transferência", subtitle: esc(dateTime(r.created_at)),
      body: `
        <div style="text-align:center;padding:4px 0 16px"><div class="label">Montante</div>
          <div class="receipt-amount num">${esc(money(r.amount, r.currency))}</div><div style="margin-top:10px">${requestChip(r.effective_status)}</div></div>
        <dl class="kv">
          <dt>Conta de origem</dt><dd class="mono">${esc(iban(r.from_iban))}</dd>
          <dt>Titular</dt><dd>${esc(who(dir, r.owner_id))}</dd>
          <dt>Conta de destino</dt><dd class="mono">${esc(iban(r.to_iban))}</dd>
          ${r.beneficiary_name ? `<dt>Beneficiário</dt><dd>${esc(r.beneficiary_name)}</dd>` : ""}
          ${r.description ? `<dt>Descrição</dt><dd>${esc(r.description)}</dd>` : ""}
          <dt>Registado por</dt><dd>${esc(who(dir, r.created_by))} · ${esc(dateTime(r.created_at))}</dd>
          <dt>Endereço IP</dt><dd class="mono">${esc(r.client_ip || "—")}</dd>
          ${r.decided_by ? `<dt>Decidido por</dt><dd>${esc(who(dir, r.decided_by))} · ${esc(dateTime(r.decided_at))}</dd>` : ""}
          ${r.decision_reason ? `<dt>Motivo</dt><dd>${esc(r.decision_reason)}</dd>` : ""}
          ${r.failure_reason ? `<dt>Falha</dt><dd>${esc(r.failure_reason)}</dd>` : ""}
          ${r.tx_id ? `<dt>Transação</dt><dd><a href="#/tx/${esc(r.tx_id)}" class="mono">${esc(r.tx_id.slice(0, 13))}…</a></dd>` : ""}
        </dl>
        ${pending && canDecide ? (ownRequest
          ? `<div class="banner banner-warn" style="margin-top:14px">${icon("alert")}<span>Registou este pedido: outro administrador tem de o decidir.</span></div>`
          : `<div class="field" style="margin-top:16px"><label for="reason">Observação / motivo <span class="muted">(obrigatório para rejeitar)</span></label>
              <input class="input" id="reason" maxlength="200"></div><div id="dec-err"></div>`) : ""}`,
      footer: pending && canDecide && !ownRequest
        ? `<button class="btn btn-secondary" id="reject">${icon("x")} Rejeitar</button><button class="btn btn-primary" id="approve">${icon("check")} Aprovar e executar</button>`
        : `<button class="btn btn-secondary" data-close>Fechar</button>`,
    });
    const decide = async (kind, btn) => {
      const reason = $("#reason", s.el).value.trim();
      if (kind === "reject" && reason.length < 3) return fieldError($("#reason", s.el), "Indique o motivo da rejeição");
      busy(btn, true);
      try {
        const res = await api(`/transfer-requests/${id}/${kind}`, { method: "POST", body: { reason: reason || undefined } });
        const st = (res.request || res).effective_status;
        toast(kind === "approve" ? (st === "EXECUTADA" ? "Aprovada e executada" : `Aprovada · ${REQUEST_STATUS[st]?.label}`) : "Pedido rejeitado", kind === "approve" && st === "FALHADA" ? "bad" : "good");
        s.close();
        draw();
      } catch (ex) {
        busy(btn, false);
        $("#dec-err", s.el).innerHTML = `<div class="banner banner-bad" style="margin-top:12px">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
      }
    };
    $("#approve", s.el)?.addEventListener("click", (e) => decide("approve", e.currentTarget));
    $("#reject", s.el)?.addEventListener("click", (e) => decide("reject", e.currentTarget));
  }

  await draw();
  void navigate;
}
