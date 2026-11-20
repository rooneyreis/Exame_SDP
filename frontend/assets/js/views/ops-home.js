// Painel do Operador: processamento de transferências.
import { api } from "../api.js";
import { dateTime, iban, money, number } from "../format.js";
import { icon } from "../icons.js";
import { esc } from "../ui.js";
import { kpi, requestChip } from "../staff.js";
import { pageHead } from "./common.js";

export async function render({ root, navigate }) {
  const [mine, limits, pendingKyc] = await Promise.all([
    api("/transfer-requests?mine=true&limit=300"), api("/admin/settings"),
    api("/admin/users?status=PENDENTE_VERIFICACAO").catch(() => []),
  ]);
  const todayStr = new Date().toDateString();
  const today = mine.filter((r) => new Date(r.created_at).toDateString() === todayStr);
  const by = (s) => mine.filter((r) => r.effective_status === s);
  const lim = Object.fromEntries(limits.map((s) => [s.key, s.value]));

  root.innerHTML = `
    ${pageHead("Painel de operações", "Registo e acompanhamento de transferências em nome dos clientes.",
      `<a class="btn btn-primary" href="#/ops/transfer">${icon("plus")} Nova transferência</a>`)}
    <div class="grid g-4 keep-2">
      ${kpi("Registadas hoje", String(today.length), `${today.filter((r) => r.effective_status === "EXECUTADA").length} concluídas`, "transfer")}
      ${kpi("A aguardar aprovação", String(by("PENDENTE_APROVACAO").length), "decisão de um administrador", "clock")}
      ${kpi("Rejeitadas / falhadas", String(by("REJEITADA").length + by("FALHADA").length), "nos seus registos", "x")}
      ${kpi("Abertura de contas", String(pendingKyc.length), "pedidos KYC pendentes", "users")}
    </div>
    <div class="grid g-main" style="margin-top:20px">
      <section class="card"><div class="card-head"><h3>As suas últimas operações</h3><a class="link" href="#/ops/requests">Ver todas</a></div>
        <ul class="list" style="margin-top:6px">${mine.slice(0, 8).map((r) => `
          <li><button class="list-item" data-go="${esc(r.tx_id || "")}" data-req="${esc(r.id)}">
            <span class="tx-icon ${r.effective_status === "EXECUTADA" ? "in" : r.effective_status === "REJEITADA" || r.effective_status === "FALHADA" ? "failed" : "out"}">${icon("transfer")}</span>
            <span class="grow"><span class="title">${esc(r.beneficiary_name || iban(r.to_iban))}</span>
              <span class="sub mono">${esc(iban(r.from_iban))} → ${esc(iban(r.to_iban))} · ${esc(dateTime(r.created_at))}</span></span>
            <span style="text-align:right"><span class="amount num">${esc(money(r.amount, r.currency))}</span><br>${requestChip(r.effective_status)}</span>
          </button></li>`).join("") || `<div class="empty"><p>Ainda não registou transferências.</p></div>`}</ul>
      </section>
      <section class="card card-pad"><h3>Regras em vigor</h3>
        <dl class="kv" style="margin-top:8px"><dt>Máximo por transferência</dt><dd class="num">${esc(number(lim.max_transfer_amount))}</dd>
          <dt>Exige aprovação a partir de</dt><dd class="num">${esc(number(lim.approval_threshold))}</dd><dt>Comissão</dt><dd>Gratuita</dd></dl>
        <p class="hint" style="margin-top:12px">${icon("info")} Abaixo do limiar, a transferência é executada de imediato. A partir do limiar fica pendente até um administrador a aprovar — nunca quem a registou.</p>
        <div class="stack" style="gap:8px;margin-top:16px">
          <a class="btn btn-secondary" href="#/ops/beneficiaries">${icon("users")} Beneficiários de clientes</a>
          <a class="btn btn-secondary" href="#/ops/accounts">${icon("wallet")} Contas e operações de caixa</a>
          <a class="btn btn-secondary" href="#/ops/kyc">${icon("check")} Abertura de contas</a>
        </div>
      </section>
    </div>`;
  root.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.go) navigate(`/tx/${encodeURIComponent(b.dataset.go)}`); else navigate("/ops/requests");
  }));
}
