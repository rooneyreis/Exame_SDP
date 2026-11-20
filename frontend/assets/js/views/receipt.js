// Comprovativo de uma operação: transferência (dados do coordenador) ou movimento local.
import { api } from "../api.js";
import { activity, myAccounts, transfer } from "../data.js";
import { dateTime, iban, kindLabel, money, number, REGIONS, regionOf, settlementLabel, time, transferStatus } from "../format.js";
import { icon } from "../icons.js";
import { beneficiaries, sentTransfers } from "../store.js";
import { $, bindCopy, esc, statusChip } from "../ui.js";
import { friendlyFailure } from "./transfer.js";
import { ROLE_LABEL, users, who } from "../staff.js";

// Eventos técnicos do 2PC -> linguagem de rastreio bancário
function trackStep(ev, tx) {
  const e = ev.event;
  const reg = (code) => REGIONS[code]?.name || code;
  const m = /_(EU|AM)$/.exec(e);
  const r = m ? m[1] : null;
  if (e === "INICIADA") return { label: "Ordem recebida e validada", desc: "Assinatura digital verificada", tone: "ok" };
  if (e === "PREPARANDO") return { label: "Reserva de fundos iniciada", desc: "As duas contas vão ser verificadas", tone: "ok" };
  if (e.startsWith("PREPARADO_")) return { label: `${reg(r)}: ${r === tx.from_region ? "débito reservado" : "crédito reservado"}`, desc: "Conta verificada e bloqueada para esta operação", tone: "ok" };
  if (e === "DECISAO_COMMIT") return { label: "Execução autorizada", desc: "Decisão registada de forma permanente", tone: "ok" };
  if (e.startsWith("COMMIT_PENDENTE_")) return { label: `${reg(r)}: confirmação adiada`, desc: "Será concluída automaticamente", tone: "warn" };
  if (e.startsWith("RECUPERACAO_COMMIT_")) return { label: `${reg(r)}: confirmação concluída`, desc: "Concluída automaticamente pelo sistema", tone: "ok" };
  if (e.startsWith("COMMIT_")) return { label: `${reg(r)}: ${r === tx.from_region ? "débito efetuado" : "crédito efetuado"}`, desc: "", tone: "ok" };
  if (e === "CONFIRMADA") return { label: "Transferência processada", desc: ev.detail?.recovered ? "Concluída após recuperação automática" : "", tone: "ok" };
  if (e.startsWith("VOTO_NAO_")) return { label: `${reg(r)}: operação recusada`, desc: friendlyFailure(ev.detail?.reason), tone: "bad" };
  if (e.startsWith("ROLLBACK_") || e.startsWith("RECUPERACAO_ROLLBACK_")) return { label: `${reg(r)}: reserva anulada`, desc: "Fundos libertados", tone: "warn" };
  if (e === "ABORTADA") return { label: "Transferência anulada", desc: "Nenhum valor foi movimentado", tone: "bad" };
  if (e === "PEDIDO_REPETIDO") return { label: "Pedido repetido recebido", desc: "Ignorado: a operação não é executada duas vezes", tone: "" };
  if (e === "LIQUIDACAO_ACEITE") return { label: "Liquidada pelo banco correspondente", desc: "Confirmação assinada recebida", tone: "ok" };
  if (e === "LIQUIDACAO_REJEITADA") return { label: "Liquidação recusada pelo banco correspondente", desc: ev.detail?.reason || "", tone: "warn" };
  if (e.startsWith("PAUSA_CHAOS")) return null;   // injeção de falhas da demonstração: não é informação para o cliente
  return { label: e.replaceAll("_", " ").toLowerCase(), desc: "", tone: "" };
}

function timeline(tx) {
  const steps = (tx.events || []).map((ev) => ({ ...trackStep(ev, tx), at: ev.at })).filter((s) => s.label);
  return `<ol class="timeline">${steps.map((s) => `
    <li class="${s.tone}"><span class="dot">${icon(s.tone === "bad" ? "x" : s.tone === "warn" ? "clock" : "check")}</span>
      <div><b>${esc(s.label)}</b>${s.desc ? `<div class="desc">${esc(s.desc)}</div>` : ""}</div>
      <time datetime="${esc(s.at)}">${esc(time(s.at))}</time></li>`).join("")}</ol>`;
}

function head(st, amount, currency, subtitle) {
  return `<div class="receipt-head">
    <div class="receipt-icon ${st.key}">${icon(st.icon)}</div>
    <div class="label">${esc(subtitle)}</div>
    <div class="receipt-amount num">${esc(money(amount, currency))}</div>
    <div style="margin-top:12px">${statusChip(st)}</div>
  </div>`;
}

function actions(ref) {
  return `<div class="row wrap no-print" style="justify-content:center;gap:10px;padding:0 24px 26px">
    <button class="btn btn-secondary" id="print">${icon("print")} Imprimir / PDF</button>
    <button class="btn btn-secondary" data-copy="${esc(ref)}" data-copy-label="Referência copiada">${icon("copy")} Copiar referência</button>
  </div>`;
}

export async function render({ root, params, claims, navigate }) {
  const txId = params.id;
  if (claims.role === "cliente") await beneficiaries.load().catch(() => []);
  let tx = await transfer(txId, { fresh: true }).catch(() => null);
  const dir = claims.role !== "cliente" ? await users().catch(() => null) : null;
  const local = sentTransfers.get(txId);

  // Movimento sem transferência visível: depósito/levantamento, ou transferência recebida
  let movement = null;
  if (!tx && claims.role === "cliente") {
    const accounts = await myAccounts();
    movement = (await activity(accounts, { limit: 300 })).find((i) => i.txId === txId);
  }
  if (!tx && !movement) {
    root.innerHTML = `<div class="card"><div class="empty"><div class="tx-icon">${icon("doc")}</div><h3>Operação não encontrada</h3>
      <p>Esta referência não existe ou não pertence às suas contas.</p><a class="btn btn-secondary" style="margin-top:14px" href="#/history">Ver movimentos</a></div></div>`;
    return;
  }

  const issued = `<div class="print-only" style="padding:20px 28px 0"><b>Global Scale Corporation</b> · Comprovativo emitido em ${esc(dateTime(Date.now()))}</div>`;
  let html;
  if (tx) {
    const st = transferStatus(tx.state);
    const name = beneficiaries.byIban(tx.to_iban)?.name || local?.beneficiary;
    const outgoing = claims.role !== "cliente" || tx.user_id === claims.sub;
    const fx = tx.from_currency !== tx.to_currency;
    html = `
      <div class="card">
        ${issued}
        ${head(st, tx.amount, tx.from_currency, `${kindLabel(tx.kind)} · ${outgoing ? "Enviada" : "Recebida"}`)}
        ${tx.state === "ABORTADA" ? `<div class="receipt-section"><div class="banner banner-bad">${icon("alert")}<span>${esc(friendlyFailure(tx.failure_reason))}</span></div></div>` : ""}
        ${st.key === "pending" ? `<div class="receipt-section"><div class="banner banner-warn">${icon("clock")}<span>Em processamento. A operação é concluída automaticamente; esta página atualiza sozinha.</span></div></div>` : ""}
        <div class="receipt-section">
          <h3>Ordenante</h3>
          <dl class="kv"><dt>Conta</dt><dd class="mono">${esc(iban(tx.from_iban))}</dd>
            <dt>Região</dt><dd>${esc(REGIONS[tx.from_region]?.name)}</dd>
            <dt>Montante debitado</dt><dd class="num">${esc(money(tx.amount, tx.from_currency))}</dd></dl>
          <h3>Beneficiário</h3>
          <dl class="kv">${name ? `<dt>Nome</dt><dd>${esc(name)}</dd>` : ""}
            <dt>Conta</dt><dd class="mono">${esc(iban(tx.to_iban))}</dd>
            <dt>Região</dt><dd>${esc(REGIONS[tx.to_region]?.name)}</dd>
            <dt>Montante creditado</dt><dd class="num">${esc(money(tx.converted_amount, tx.to_currency))}</dd></dl>
          <h3>Detalhes</h3>
          <dl class="kv">
            ${fx ? `<dt>Taxa de câmbio</dt><dd class="num">1 ${esc(tx.from_currency)} = ${esc(number(tx.fx_rate, 6))} ${esc(tx.to_currency)}</dd>` : ""}
            <dt>Comissão</dt><dd class="num">${esc(money(0, tx.from_currency))}</dd>
            ${local?.description ? `<dt>Descrição</dt><dd>${esc(local.description)}</dd>` : ""}
            ${dir ? `<dt>Iniciada por</dt><dd>${esc(who(dir, tx.initiated_by || tx.user_id))} <span class="hint">(${esc(ROLE_LABEL[tx.initiated_role || "cliente"])})</span></dd>
              <dt>Titular da conta</dt><dd>${esc(who(dir, tx.user_id))}</dd>
              <dt>Aprovada por</dt><dd>${tx.approved_by ? esc(who(dir, tx.approved_by)) : `<span class="muted">não exigida</span>`}</dd>` : ""}
            <dt>Data da ordem</dt><dd>${esc(dateTime(tx.created_at))}</dd>
            <dt>Última atualização</dt><dd>${esc(dateTime(tx.updated_at))}</dd>
            ${tx.kind === "DISTRIBUIDA" ? `<dt>Liquidação</dt><dd>${esc(settlementLabel(tx.settlement_status))}</dd>` : ""}
            <dt>Referência</dt><dd class="mono">${esc(tx.tx_id)} <button class="copy no-print" data-copy="${esc(tx.tx_id)}" aria-label="Copiar referência">${icon("copy")}</button></dd>
          </dl>
          <h3>Rastreio do processamento</h3>
          ${timeline(tx)}
          <h3>Integridade</h3>
          <p class="hint" style="display:flex;gap:8px">${icon("fingerprint")}<span>Ordem assinada digitalmente (Ed25519). Impressão digital SHA-256 do pedido:<br><span class="mono" style="word-break:break-all">${esc(tx.request_sha256 || "—")}</span></span></p>
        </div>
        ${actions(tx.tx_id)}
      </div>`;
  } else {
    const m = movement;
    html = `
      <div class="card">
        ${issued}
        ${head(m.status, m.amount, m.currency, m.category)}
        <div class="receipt-section"><dl class="kv">
          <dt>Conta</dt><dd class="mono">${esc(iban(m.account))}</dd>
          <dt>Operação</dt><dd>${esc(m.category)}</dd>
          <dt>Montante</dt><dd class="num">${esc(money(m.direction === "in" ? m.amount : -m.amount, m.currency, { sign: true }))}</dd>
          <dt>Saldo após operação</dt><dd class="num">${esc(money(m.balanceAfter, m.currency))}</dd>
          <dt>Data</dt><dd>${esc(dateTime(m.date))}</dd>
          <dt>Referência</dt><dd class="mono">${esc(m.txId)}</dd>
        </dl>
        ${m.origin === "TRANSFERENCIA" ? `<p class="hint" style="margin-top:14px">Os dados do ordenante de transferências recebidas são reservados ao banco do ordenante.</p>` : ""}
        </div>
        ${actions(m.txId)}
      </div>`;
  }

  root.innerHTML = `
    <div class="receipt">
      <div class="row between no-print" style="margin:4px 0 18px">
        <a href="#/${claims.role === "cliente" ? "history" : "admin/transfers"}" class="btn btn-ghost">${icon("chevronLeft")} Voltar</a>
        <span class="hint">${icon("lock")} Documento gerado a partir do registo do banco</span>
      </div>
      ${html}
    </div>`;
  $("#print", root)?.addEventListener("click", () => window.print());
  bindCopy(root);

  // Atualiza sozinho enquanto estiver pendente
  if (tx && transferStatus(tx.state).key === "pending") {
    const t = setTimeout(() => { if (location.hash.includes(txId)) render({ root, params, claims, navigate }); }, 3000);
    window.addEventListener("hashchange", () => clearTimeout(t), { once: true });
  }
  void api;
}
