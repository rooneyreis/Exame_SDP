import { api, newIdempotencyKey } from "../api.js";
import { convert, fxRates, movements, myAccounts } from "../data.js";
import { iban as fmtIban, kindLabel, money, number, REGIONS, regionOf } from "../format.js";
import { icon } from "../icons.js";
import { beneficiaries, sentTransfers } from "../store.js";
import { $, $$, busy, esc, fieldError, sheet, statusChip } from "../ui.js";
import { transferStatus } from "../format.js";
import { pageHead } from "./common.js";

const MAX_PER_TRANSFER = 10000;

export function friendlyFailure(reason = "") {
  const r = reason.toLowerCase();
  if (r.includes("saldo insuficiente")) return "Saldo insuficiente na conta de origem.";
  if (r.includes("limite diário")) return "Ultrapassa o limite diário de transferências desta conta.";
  if (r.includes("não existe")) return "A conta de destino não existe. Confirme o IBAN.";
  if (r.includes("bloqueada") && r.includes("destino")) return "A conta de destino não pode receber fundos de momento.";
  if (r.includes("lock_timeout")) return "A conta estava ocupada com outra operação. Tente novamente dentro de instantes.";
  if (r.includes("indisponível") || r.includes("timeout") || r.includes("presumed abort")) return "O banco da conta de destino não respondeu a tempo. A operação foi anulada e nenhum valor saiu da sua conta.";
  return "A operação não pôde ser concluída e foi anulada. Nenhum valor saiu da sua conta.";
}

function validIban(v) { return /^GS-(EU|AM)-\d{8}$/.test(v); }

function normalizeIban(v) {
  const s = v.toUpperCase().replace(/[\s]/g, "");
  const m = /^GS-?(EU|AM)-?(\d{8})$/.exec(s);
  return m ? `GS-${m[1]}-${m[2]}` : s;
}

export async function render({ root, query, navigate }) {
  const [accounts, rates] = await Promise.all([myAccounts(), fxRates()]);
  const active = accounts.filter((a) => a.status === "ATIVA");
  if (!active.length) {
    root.innerHTML = `${pageHead("Transferir")}<div class="card"><div class="empty"><h3>Sem contas ativas</h3></div></div>`;
    return;
  }
  await beneficiaries.load().catch(() => []);
  const saved = beneficiaries.all();
  const state = {
    from: active.find((a) => a.iban === query.get("from")) || active[0],
    mode: query.get("to") ? "new" : saved.length ? "saved" : "new",
    to: query.get("to") || "", name: query.get("name") || "", save: !query.get("to") || !beneficiaries.byIban(query.get("to") || ""),
    amount: "", description: "", todayDebits: 0,
  };
  const pre = beneficiaries.byIban(state.to);
  if (pre) { state.mode = "saved"; state.name = pre.name; }

  root.innerHTML = `
    ${pageHead("Transferir", "Para contas Global Scale na Europa e na América. As transferências internacionais são convertidas ao câmbio do dia.")}
    <div class="transfer-layout">
      <form class="card" id="tf" novalidate>
        <div class="step done" data-step="1">
          <span class="step-num">1</span>
          <div class="step-body">
            <h3>De</h3>
            <div class="choice-grid" role="radiogroup" aria-label="Conta de origem">
              ${active.map((a) => `<button type="button" class="choice" role="radio" data-from="${esc(a.iban)}" aria-checked="${a.iban === state.from.iban}">
                <span class="cur" style="display:inline-grid;place-items:center;width:36px;height:36px;border-radius:10px;background:var(--surface-sunken);font-weight:700;font-size:.72rem">${esc(a.currency)}</span>
                <span class="grow"><b class="num">${esc(money(a.balance, a.currency))}</b><span class="mono">${esc(fmtIban(a.iban))}</span></span></button>`).join("")}
            </div>
          </div>
        </div>

        <div class="step" data-step="2">
          <span class="step-num">2</span>
          <div class="step-body">
            <div class="row between wrap"><h3>Para</h3>
              <div class="segmented" role="group" aria-label="Tipo de destinatário">
                <button type="button" data-mode="saved" aria-pressed="${state.mode === "saved"}" ${saved.length ? "" : "disabled"}>Beneficiários</button>
                <button type="button" data-mode="new" aria-pressed="${state.mode === "new"}">Novo destinatário</button>
              </div>
            </div>
            <div id="to-saved" ${state.mode === "saved" ? "" : "hidden"}>
              <div class="choice-grid" role="radiogroup" aria-label="Beneficiário">
                ${saved.map((b) => `<button type="button" class="choice" role="radio" data-ben="${esc(b.iban)}" aria-checked="${b.iban === state.to}">
                  <span class="avatar">${esc(b.name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase())}</span>
                  <span class="grow"><b>${esc(b.name)}</b><span class="mono">${esc(fmtIban(b.iban))}</span></span>
                  ${b.favorite ? icon("star") : ""}</button>`).join("")}
              </div>
            </div>
            <div id="to-new" class="stack" style="gap:14px" ${state.mode === "new" ? "" : "hidden"}>
              <div class="grid g-2" style="gap:14px">
                <div class="field"><label for="to-iban">IBAN do destinatário</label>
                  <input class="input mono" id="to-iban" placeholder="GS-EU-00000000" autocomplete="off" spellcheck="false" value="${esc(state.mode === "new" ? state.to : "")}">
                  <p class="hint" id="iban-hint">Formato GS-EU-######## (Europa) ou GS-AM-######## (América)</p></div>
                <div class="field"><label for="to-name">Nome do beneficiário</label>
                  <input class="input" id="to-name" placeholder="Nome completo" autocomplete="off" value="${esc(state.mode === "new" ? state.name : "")}"></div>
              </div>
              <label class="row" style="gap:10px;font-size:.88rem;cursor:pointer"><input type="checkbox" id="save-ben" ${state.save ? "checked" : ""} style="width:18px;height:18px;accent-color:var(--accent)"> Guardar nos meus beneficiários</label>
            </div>
          </div>
        </div>

        <div class="step" data-step="3">
          <span class="step-num">3</span>
          <div class="step-body">
            <h3>Montante</h3>
            <div class="field">
              <label for="amount" class="sr-only">Montante</label>
              <div class="input-affix"><input class="input amount-input num" id="amount" inputmode="decimal" placeholder="0,00" autocomplete="off"><span class="affix" id="amount-cur">${esc(state.from.currency)}</span></div>
              <div class="row wrap" style="gap:8px">${[50, 100, 250, 1000].map((v) => `<button type="button" class="btn btn-secondary btn-sm" data-quick="${v}">${esc(money(v, state.from.currency))}</button>`).join("")}</div>
              <p class="hint" id="limit-hint">Máximo ${esc(money(MAX_PER_TRANSFER, state.from.currency))} por transferência.</p>
            </div>
            <div class="field"><label for="desc">Descrição <span class="muted">(opcional)</span></label>
              <input class="input" id="desc" maxlength="80" placeholder="Ex.: Renda de novembro"></div>
            <div id="form-error"></div>
            <button class="btn btn-primary btn-lg" id="review" type="submit">Rever transferência ${icon("arrowRight")}</button>
          </div>
        </div>
      </form>

      <aside class="card card-pad summary" aria-label="Resumo" id="summary"></aside>
    </div>`;

  const $in = (id) => $(`#${id}`, root);

  function toIban() { return state.mode === "saved" ? state.to : normalizeIban($in("to-iban").value.trim()); }
  function toName() { return state.mode === "saved" ? (beneficiaries.byIban(state.to)?.name || "") : $in("to-name").value.trim(); }
  function amountValue() { return Number(($in("amount").value || "").replace(/\s/g, "").replace(",", ".")); }

  function estimate() {
    const dest = toIban();
    const region = regionOf(dest);
    const destCur = region ? REGIONS[region].currency : null;
    const amount = amountValue();
    const kind = region ? (region === regionOf(state.from.iban) ? "LOCAL" : "DISTRIBUIDA") : null;
    const rate = destCur ? (destCur === state.from.currency ? 1 : rates[state.from.currency]?.[destCur]) : null;
    return { dest, region, destCur, amount, kind, rate, receives: rate && amount ? convert(amount, state.from.currency, destCur, rates) : null };
  }

  function drawSummary() {
    const e = estimate();
    const fromR = REGIONS[regionOf(state.from.iban)];
    const toR = e.region ? REGIONS[e.region] : null;
    const name = toName();
    const remaining = Number(state.from.daily_limit) - state.todayDebits;
    $("#summary", root).innerHTML = `
      <h3>Resumo</h3>
      <div class="route" style="margin-top:14px">
        <div class="end"><b>${esc(fromR?.name || "")}</b><span class="mono">${esc(fmtIban(state.from.iban))}</span></div>
        <span class="arrow">${icon("arrowRight")}</span>
        <div class="end" style="text-align:right"><b>${esc(name || (toR ? toR.name : "Destinatário"))}</b><span class="mono">${esc(e.dest && validIban(e.dest) ? fmtIban(e.dest) : "—")}</span></div>
      </div>
      <div style="margin:18px 0 4px" class="label">Envia</div>
      <div class="total num">${esc(money(e.amount || 0, state.from.currency))}</div>
      <dl class="kv" style="margin-top:12px">
        <dt>Tipo</dt><dd>${e.kind ? `<span class="chip ${e.kind === "DISTRIBUIDA" ? "chip-accent" : ""}">${icon(e.kind === "DISTRIBUIDA" ? "globe" : "bank")}${esc(kindLabel(e.kind))}</span>` : "—"}</dd>
        <dt>Câmbio</dt><dd class="num">${e.rate && e.rate !== 1 ? `1 ${esc(state.from.currency)} = ${esc(number(e.rate, 4))} ${esc(e.destCur)}` : e.rate === 1 ? "Sem conversão" : "—"}</dd>
        <dt>O beneficiário recebe</dt><dd class="num">${e.receives != null ? `${e.rate !== 1 ? "≈ " : ""}${esc(money(e.receives, e.destCur))}` : "—"}</dd>
        <dt>Comissão</dt><dd class="num">${esc(money(0, state.from.currency))}</dd>
        <dt>Disponível hoje</dt><dd class="num">${esc(money(Math.max(remaining, 0), state.from.currency))}</dd>
      </dl>
      <div class="banner banner-info" style="margin-top:16px">${icon(e.kind === "DISTRIBUIDA" ? "globe" : e.kind ? "bolt" : "info")}
        <span>${e.kind === "DISTRIBUIDA"
          ? `Débito em ${esc(fromR?.city || "")} e crédito em ${esc(toR?.city || "")} confirmados em conjunto: ou acontecem os dois, ou nenhum. O câmbio é fixado no momento da execução; a moeda final depende da conta de destino.`
          : e.kind ? "Transferência imediata entre contas da mesma região."
          : "Indique o destinatário: as contas GS-EU estão em Lisboa e as GS-AM em Nova Iorque."}</span></div>`;
  }

  async function loadTodayDebits() {
    try {
      const ms = await movements(state.from.iban, 200);
      const start = new Date(); start.setHours(0, 0, 0, 0);
      state.todayDebits = ms.filter((m) => m.type === "DEBITO" && m.origin === "TRANSFERENCIA" && new Date(m.created_at) >= start)
        .reduce((s, m) => s + Number(m.amount), 0);
    } catch { state.todayDebits = 0; }
    drawSummary();
  }

  function markSteps() {
    const e = estimate();
    $(`[data-step="2"]`, root).classList.toggle("done", validIban(e.dest));
    $(`[data-step="3"]`, root).classList.toggle("done", e.amount > 0);
  }

  $$("[data-from]", root).forEach((b) => b.addEventListener("click", () => {
    state.from = active.find((a) => a.iban === b.dataset.from);
    $$("[data-from]", root).forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    $in("amount-cur").textContent = state.from.currency;
    loadTodayDebits();
  }));
  $$("[data-mode]", root).forEach((b) => b.addEventListener("click", () => {
    state.mode = b.dataset.mode;
    $$("[data-mode]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $in("to-saved").hidden = state.mode !== "saved";
    $in("to-new").hidden = state.mode !== "new";
    drawSummary(); markSteps();
  }));
  $$("[data-ben]", root).forEach((b) => b.addEventListener("click", () => {
    state.to = b.dataset.ben;
    $$("[data-ben]", root).forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    drawSummary(); markSteps();
  }));
  $$("[data-quick]", root).forEach((b) => b.addEventListener("click", () => { $in("amount").value = number(b.dataset.quick); drawSummary(); markSteps(); }));
  ["to-iban", "to-name", "amount"].forEach((id) => $in(id).addEventListener("input", () => { drawSummary(); markSteps(); }));
  $in("to-iban").addEventListener("blur", () => {
    const v = normalizeIban($in("to-iban").value.trim());
    if (v) $in("to-iban").value = v;
    fieldError($in("to-iban"), !v || validIban(v) ? null : "IBAN inválido. Use GS-EU-######## ou GS-AM-########.");
    drawSummary();
  });

  drawSummary(); markSteps(); loadTodayDebits();

  $in("tf").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const e = estimate();
    const name = toName();
    let ok = true;
    const err = $in("form-error"); err.innerHTML = "";
    if (state.mode === "new") {
      fieldError($in("to-iban"), validIban(e.dest) ? null : "IBAN inválido"); ok &&= validIban(e.dest);
    } else if (!validIban(e.dest)) { err.innerHTML = `<p class="error-text">${icon("alert")}Escolha um beneficiário.</p>`; ok = false; }
    if (e.dest === state.from.iban) { err.innerHTML = `<p class="error-text">${icon("alert")}A conta de destino tem de ser diferente da de origem.</p>`; ok = false; }
    const amountOk = e.amount > 0 && e.amount <= MAX_PER_TRANSFER && Math.round(e.amount * 100) === e.amount * 100;
    fieldError($in("amount"), amountOk ? (e.amount > Number(state.from.balance) ? "Saldo insuficiente" : null)
      : e.amount > MAX_PER_TRANSFER ? `Máximo ${money(MAX_PER_TRANSFER, state.from.currency)} por transferência` : "Indique um montante válido (até 2 casas decimais)");
    ok &&= amountOk && e.amount <= Number(state.from.balance);
    if (!ok) return;
    review({ ...e, name, description: $in("desc").value.trim(), save: state.mode === "new" && $in("save-ben").checked });
  });

  function review(e) {
    const key = newIdempotencyKey();          // uma chave por intenção: repetir nunca duplica
    const s = sheet({
      title: "Confirmar transferência",
      body: `
        <div style="text-align:center;padding:6px 0 18px">
          <div class="label">Vai enviar</div>
          <div class="receipt-amount num">${esc(money(e.amount, state.from.currency))}</div>
          <div class="soft" style="margin-top:6px">para <b>${esc(e.name || fmtIban(e.dest))}</b></div>
        </div>
        <dl class="kv">
          <dt>Conta de origem</dt><dd class="mono">${esc(fmtIban(state.from.iban))}</dd>
          <dt>Conta de destino</dt><dd class="mono">${esc(fmtIban(e.dest))}</dd>
          <dt>Tipo</dt><dd>${esc(kindLabel(e.kind))} · ${esc(REGIONS[regionOf(state.from.iban)].name)} → ${esc(REGIONS[e.region].name)}</dd>
          ${e.rate && e.rate !== 1 ? `<dt>Recebe (estimativa)</dt><dd class="num">≈ ${esc(money(e.receives, e.destCur))}</dd>` : ""}
          ${e.description ? `<dt>Descrição</dt><dd>${esc(e.description)}</dd>` : ""}
          <dt>Comissão</dt><dd>Gratuita</dd>
        </dl>
        <p class="hint" style="margin-top:14px;display:flex;gap:8px">${icon("shield")}<span>O pedido é assinado digitalmente antes de sair do nosso servidor. Se a ligação falhar, pode repetir com segurança: a operação nunca é executada duas vezes.</span></p>`,
      footer: `<button class="btn btn-secondary" data-close>Corrigir</button><button class="btn btn-primary" id="confirm">${icon("lock")} Confirmar e enviar</button>`,
    });
    $("#confirm", s.el).addEventListener("click", async (ev) => {
      busy(ev.currentTarget, true, "A processar…");
      const result = await submit(e, key);
      s.close();
      showResult(result, e, key);
    });
  }

  async function submit(e, key) {
    const body = { from_iban: state.from.iban, to_iban: e.dest, amount: e.amount.toFixed(2) };
    try {
      return await api("/transfers", { method: "POST", body, headers: { "Idempotency-Key": key }, raw: true });
    } catch (ex) {
      return { ok: false, status: ex.status || 0, data: { detail: ex.message } };
    }
  }

  function showResult(r, e, key) {
    const d = r.data || {};
    const txId = d.tx_id || d.detail?.tx_id;
    if (txId) {
      sentTransfers.add({ tx_id: txId, from_iban: state.from.iban, to_iban: e.dest, amount: e.amount.toFixed(2), currency: state.from.currency,
        beneficiary: e.name, description: e.description, state: d.state || "INICIADA", key });
    }
    if (e.save && (r.status === 201 || r.status === 200 || r.status === 202) && !beneficiaries.byIban(e.dest)) {
      beneficiaries.save({ name: e.name || fmtIban(e.dest), iban: e.dest }).catch(() => {});
    }
    beneficiaries.touch(e.dest);

    let kind, title, text, extra = "";
    if (r.status === 201 || r.status === 200) {
      kind = "done"; title = "Transferência processada";
      text = `${money(e.amount, state.from.currency)} enviados para ${e.name || fmtIban(e.dest)}.`;
      if (d.kind === "DISTRIBUIDA") extra = `O beneficiário recebeu <b class="num">${esc(money(d.converted_amount, d.to_currency))}</b> ao câmbio de ${esc(number(d.fx_rate, 4))}.`;
    } else if (r.status === 202 || r.status === 503) {
      kind = "pending"; title = "Transferência em processamento";
      text = r.status === 503
        ? "Não recebemos confirmação a tempo. A sua ordem está registada e protegida contra duplicação: pode verificar o estado ou voltar a tentar."
        : "O débito está confirmado e o crédito no banco de destino será concluído automaticamente nos próximos instantes.";
    } else if (r.status === 422 && d.state === "ABORTADA") {
      kind = "failed"; title = "Transferência não realizada"; text = friendlyFailure(d.failure_reason);
    } else {
      kind = "failed"; title = "Não foi possível enviar";
      text = r.status === 404 ? "A conta de destino não existe. Confirme o IBAN." : (typeof d.detail === "string" ? d.detail : "Ocorreu um erro. Nenhum valor foi debitado.");
    }
    const st = { done: transferStatus("CONFIRMADA"), pending: transferStatus("PREPARANDO"), failed: transferStatus("ABORTADA") }[kind];
    root.innerHTML = `
      <div class="receipt view-enter">
        <div class="card">
          <div class="receipt-head">
            <div class="receipt-icon ${kind}">${icon(st.icon)}</div>
            <h1 style="font-size:1.6rem">${esc(title)}</h1>
            <div class="receipt-amount num" style="margin-top:14px">${esc(money(e.amount, state.from.currency))}</div>
            <p class="soft" style="margin-top:10px;max-width:460px;margin-inline:auto">${esc(text)}</p>
            ${extra ? `<p class="soft" style="margin-top:6px">${extra}</p>` : ""}
            <div style="margin-top:14px">${statusChip(st)}</div>
          </div>
          <div class="receipt-section"><dl class="kv">
            <dt>Para</dt><dd>${esc(e.name || "—")}<br><span class="mono muted">${esc(fmtIban(e.dest))}</span></dd>
            <dt>De</dt><dd class="mono">${esc(fmtIban(state.from.iban))}</dd>
            ${txId ? `<dt>Referência</dt><dd class="mono">${esc(txId)}</dd>` : ""}
          </dl></div>
          <div class="sheet-foot" style="justify-content:center;flex-wrap:wrap">
            ${txId && kind !== "failed" || (txId && d.state) ? `<a class="btn btn-secondary" href="#/tx/${encodeURIComponent(txId)}">${icon("doc")} Ver comprovativo</a>` : ""}
            ${r.status === 503 ? `<button class="btn btn-secondary" id="retry">${icon("refresh")} Tentar novamente</button>` : ""}
            <a class="btn btn-primary" href="#/dashboard">Concluir</a>
          </div>
        </div>
      </div>`;
    $("#retry", root)?.addEventListener("click", async (ev) => {
      busy(ev.currentTarget, true, "A repetir…");
      showResult(await submit(e, key), e, key);   // mesma Idempotency-Key: nunca duplica
    });
    void navigate;
  }
}
