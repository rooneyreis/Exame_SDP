// Nova transferência registada por um Operador em nome de um cliente.
// Abaixo do limiar é executada pelo 2PC de imediato; acima fica pendente de aprovação.
import { api } from "../api.js";
import { fxRates, convert } from "../data.js";
import { iban as fmtIban, kindLabel, money, number, REGIONS, regionOf, IBAN_RE, IBAN_LOOSE_RE } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, esc, fieldError, sheet } from "../ui.js";
import { requestChip, users, who } from "../staff.js";
import { friendlyFailure } from "./transfer.js";
import { pageHead } from "./common.js";

const norm = (v) => v.toUpperCase().replace(/\s/g, "").replace(IBAN_LOOSE_RE, "GS-$1-$2");
const valid = (v) => IBAN_RE.test(v);

export async function render({ root, navigate }) {
  const [rates, limits, dir] = await Promise.all([fxRates(), api("/admin/settings"), users()]);
  const lim = Object.fromEntries(limits.map((s) => [s.key, Number(s.value)]));
  const st = { source: null, bens: [], to: "", name: "" };

  root.innerHTML = `
    ${pageHead("Nova transferência", "Registo ao balcão, em nome do titular da conta de origem.")}
    <div class="transfer-layout">
      <form class="card" id="f" novalidate>
        <div class="step" data-step="1"><span class="step-num">1</span><div class="step-body">
          <h3>Conta de origem</h3>
          <div class="field"><label for="src">IBAN do cliente</label>
            <div class="row"><input class="input mono" id="src" placeholder="GS-EU-00000001" spellcheck="false" autocomplete="off">
              <button class="btn btn-secondary" type="button" id="lookup">${icon("search")} Validar</button></div></div>
          <div id="src-info"></div>
        </div></div>
        <div class="step" data-step="2"><span class="step-num">2</span><div class="step-body">
          <h3>Destino</h3>
          <div id="bens" class="choice-grid"></div>
          <div class="grid g-2" style="gap:14px">
            <div class="field"><label for="dst">IBAN de destino</label><input class="input mono" id="dst" placeholder="GS-AM-00000000" spellcheck="false" autocomplete="off"></div>
            <div class="field"><label for="ben">Nome do beneficiário</label><input class="input" id="ben" maxlength="120"></div>
          </div>
        </div></div>
        <div class="step" data-step="3"><span class="step-num">3</span><div class="step-body">
          <h3>Montante</h3>
          <div class="field"><div class="input-affix"><input class="input amount-input num" id="amount" inputmode="decimal" placeholder="0,00"><span class="affix" id="cur">—</span></div>
            <p class="hint">Máximo ${esc(number(lim.max_transfer_amount))} · aprovação obrigatória a partir de ${esc(number(lim.approval_threshold))} (na moeda da conta de origem).</p></div>
          <div class="field"><label for="desc">Descrição / referência do cliente</label><input class="input" id="desc" maxlength="140"></div>
          <div id="err"></div>
          <button class="btn btn-primary btn-lg" type="submit">Validar transferência ${icon("arrowRight")}</button>
        </div></div>
      </form>
      <aside class="card card-pad summary" id="summary"></aside>
    </div>`;

  const $in = (id) => $(`#${id}`, root);
  const amount = () => Number(($in("amount").value || "").replace(/\s/g, "").replace(",", "."));

  function estimate() {
    const dst = norm($in("dst").value.trim());
    const region = valid(dst) ? regionOf(dst) : null;
    const destCur = region ? REGIONS[region].currency : null;
    const from = st.source;
    const rate = from && destCur ? (destCur === from.currency ? 1 : rates[from.currency]?.[destCur]) : null;
    const kind = from && region ? (regionOf(from.iban) === region ? "LOCAL" : "DISTRIBUIDA") : null;
    return { dst, region, destCur, rate, kind, amount: amount(), receives: rate && amount() ? convert(amount(), from.currency, destCur, rates) : null };
  }

  function summary() {
    const e = estimate(), from = st.source;
    const needsApproval = from && e.amount >= lim.approval_threshold;
    $("#summary", root).innerHTML = `<h3>Validação</h3>
      <dl class="kv" style="margin-top:8px">
        <dt>Titular</dt><dd>${from ? esc(who(dir, from.user_id)) : "—"}</dd>
        <dt>Saldo disponível</dt><dd class="num">${from ? esc(money(from.balance, from.currency)) : "—"}</dd>
        <dt>Tipo</dt><dd>${e.kind ? `<span class="chip ${e.kind === "DISTRIBUIDA" ? "chip-accent" : ""}">${esc(kindLabel(e.kind))}</span>` : "—"}</dd>
        <dt>Câmbio</dt><dd class="num">${e.rate && e.rate !== 1 ? `1 ${esc(from.currency)} = ${esc(number(e.rate, 4))} ${esc(e.destCur)}` : e.rate === 1 ? "Sem conversão" : "—"}</dd>
        <dt>Beneficiário recebe</dt><dd class="num">${e.receives != null ? `${e.rate !== 1 ? "≈ " : ""}${esc(money(e.receives, e.destCur))}` : "—"}</dd>
        <dt>Comissão</dt><dd>Gratuita</dd>
      </dl>
      <div class="banner ${needsApproval ? "banner-warn" : "banner-info"}" style="margin-top:14px">${icon(needsApproval ? "clock" : "bolt")}
        <span>${needsApproval ? "Este montante exige aprovação de um administrador antes de ser executado." : "Executada de imediato após submissão."}</span></div>`;
  }

  async function lookup() {
    const v = norm($in("src").value.trim());
    $in("src").value = v;
    if (!valid(v)) return fieldError($in("src"), "IBAN inválido");
    try {
      const acc = await api(`/accounts/${encodeURIComponent(v)}`);
      fieldError($in("src"), null);
      st.source = acc;
      $in("cur").textContent = acc.currency;
      $in("src-info").innerHTML = `<div class="banner ${acc.status === "ATIVA" ? "banner-good" : "banner-bad"}">${icon(acc.status === "ATIVA" ? "check" : "alert")}
        <span><b>${esc(who(dir, acc.user_id))}</b> · ${esc(acc.currency)} · saldo ${esc(money(acc.balance, acc.currency))}${acc.status !== "ATIVA" ? " · conta bloqueada" : ""}</span></div>`;
      $(`[data-step="1"]`, root).classList.add("done");
      st.bens = await api(`/admin/beneficiaries?owner_id=${acc.user_id}`).catch(() => []);
      $in("bens").innerHTML = st.bens.map((b) => `<button type="button" class="choice" role="radio" aria-checked="false" data-ben="${esc(b.iban)}" data-name="${esc(b.name)}">
        ${icon("user")}<span class="grow"><b>${esc(b.name)}</b><span class="mono">${esc(fmtIban(b.iban))}</span></span></button>`).join("");
      $$("[data-ben]", root).forEach((b) => b.addEventListener("click", () => {
        $$("[data-ben]", root).forEach((x) => x.setAttribute("aria-checked", String(x === b)));
        $in("dst").value = b.dataset.ben; $in("ben").value = b.dataset.name; summary();
      }));
      summary();
    } catch (ex) {
      st.source = null;
      fieldError($in("src"), ex.status === 404 ? "Conta não encontrada" : ex.message);
    }
  }

  $in("lookup").addEventListener("click", lookup);
  $in("src").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); lookup(); } });
  ["dst", "amount"].forEach((id) => $in(id).addEventListener("input", summary));
  summary();

  $in("f").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const e = estimate();
    let ok = !!st.source;
    if (!st.source) fieldError($in("src"), "Valide a conta de origem");
    fieldError($in("dst"), valid(e.dst) && e.dst !== st.source?.iban ? null : "IBAN de destino inválido ou igual à origem");
    ok &&= valid(e.dst) && e.dst !== st.source?.iban;
    const amountOk = e.amount > 0 && e.amount <= lim.max_transfer_amount && Math.round(e.amount * 100) === e.amount * 100;
    fieldError($in("amount"), !amountOk ? `Montante inválido (máx. ${number(lim.max_transfer_amount)})` : st.source && e.amount > Number(st.source.balance) ? "Saldo insuficiente" : null);
    ok &&= amountOk && e.amount <= Number(st.source?.balance || 0);
    if (!ok) return;
    const needsApproval = e.amount >= lim.approval_threshold;
    const s = sheet({
      title: needsApproval ? "Submeter para aprovação" : "Confirmar transferência",
      body: `<div style="text-align:center;padding:4px 0 16px"><div class="label">Montante</div><div class="receipt-amount num">${esc(money(e.amount, st.source.currency))}</div></div>
        <dl class="kv"><dt>De</dt><dd><span class="mono">${esc(fmtIban(st.source.iban))}</span><br><span class="hint">${esc(who(dir, st.source.user_id))}</span></dd>
          <dt>Para</dt><dd><span class="mono">${esc(fmtIban(e.dst))}</span>${$in("ben").value ? `<br><span class="hint">${esc($in("ben").value)}</span>` : ""}</dd>
          <dt>Tipo</dt><dd>${esc(kindLabel(e.kind))}</dd>
          ${needsApproval ? `<dt>Aprovação</dt><dd>Obrigatória (≥ ${esc(number(lim.approval_threshold))})</dd>` : ""}</dl>
        <p class="hint" style="margin-top:12px">${icon("shield")} Fica registado que foi você a submeter esta ordem (com data, hora e IP).</p>`,
      footer: `<button class="btn btn-secondary" data-close>Corrigir</button><button class="btn btn-primary" id="go">${icon("lock")} ${needsApproval ? "Submeter para aprovação" : "Confirmar e enviar"}</button>`,
    });
    $("#go", s.el).addEventListener("click", async (b) => {
      busy(b.currentTarget, true, "A processar…");
      try {
        const r = await api("/transfer-requests", { method: "POST", body: { from_iban: st.source.iban, to_iban: e.dst, amount: e.amount.toFixed(2),
          beneficiary_name: $in("ben").value.trim() || undefined, description: $in("desc").value.trim() || undefined } });
        s.close();
        result(r);
      } catch (ex) {
        busy(b.currentTarget, false);
        s.close();
        $in("err").innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.message)}</span></div>`;
      }
    });
  });

  function result(r) {
    const req = r.request;
    const kind = req.effective_status === "EXECUTADA" ? "done" : req.effective_status === "FALHADA" ? "failed" : "pending";
    const title = { EXECUTADA: "Transferência executada", FALHADA: "Transferência não realizada", PENDENTE_APROVACAO: "Submetida para aprovação", EM_EXECUCAO: "Em processamento" }[req.effective_status];
    root.innerHTML = `<div class="receipt view-enter"><div class="card"><div class="receipt-head">
      <div class="receipt-icon ${kind}">${icon(kind === "done" ? "check" : kind === "failed" ? "x" : "clock")}</div>
      <h1 style="font-size:1.6rem">${esc(title)}</h1><div class="receipt-amount num" style="margin-top:12px">${esc(money(req.amount, req.currency))}</div>
      <p class="soft" style="margin-top:10px">${req.effective_status === "FALHADA" ? esc(friendlyFailure(req.failure_reason)) : req.effective_status === "PENDENTE_APROVACAO" ? "Um administrador irá rever e decidir. Pode acompanhar em Operações." : esc(r.message)}</p>
      <div style="margin-top:12px">${requestChip(req.effective_status)}</div></div>
      <div class="sheet-foot" style="justify-content:center;flex-wrap:wrap">
        ${req.tx_id ? `<a class="btn btn-secondary" href="#/tx/${esc(req.tx_id)}">${icon("doc")} Ver comprovativo</a>` : ""}
        <a class="btn btn-secondary" href="#/ops/requests">${icon("history")} Operações</a>
        <a class="btn btn-primary" href="#/ops/transfer" id="again">Nova transferência</a></div></div></div>`;
    $("#again", root).addEventListener("click", (ev) => { ev.preventDefault(); render({ root, navigate }); });
  }
}
