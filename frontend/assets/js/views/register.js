// Abrir conta: assistente em três passos (dados pessoais → região e moeda → segurança),
// com um painel lateral útil (regiões, moedas e o processo até a conta ficar ativa) e um
// ecrã final que explica o que acontece a seguir. Só chama POST /auth/register.
import { api } from "../api.js";
import { CURRENCY_NAMES, REGION_CODES, REGIONS, regionName } from "../format.js";
import { icon, LOGO } from "../icons.js";
import { $, $$, busy, esc, fieldError } from "../ui.js";

const RULES = [
  [/.{8,}/, "8 ou mais caracteres"],
  [/[A-Z]/, "Uma letra maiúscula"],
  [/[0-9]/, "Um número"],
  [/[^A-Za-z0-9]/, "Um símbolo"],
];

// Indicativo e exemplo de número por região (o placeholder do telemóvel acompanha a escolha).
const PHONE = {
  EU: { code: "+351", example: "912 345 678", country: "Portugal" },
  AM: { code: "+1", example: "202 555 0143", country: "EUA" },
  AF: { code: "+258", example: "84 123 4567", country: "Moçambique" },
};

const STEPS = [
  ["Dados pessoais", "Identificação"],
  ["Região e moeda", "Onde fica a conta"],
  ["Segurança", "Palavra-passe e revisão"],
];

const PLURAL = { EUR: "euros", USD: "dólares", MZN: "meticais" };

/** "dd/mm/aaaa" -> Date (ou null) */
function parseDate(v) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(v || "");
  if (!m) return null;
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d ? date : null;
}

function regHero() {
  return `
  <section class="auth-hero reg-hero">
    <a class="brand" href="#/login"><span class="brand-mark">${LOGO}</span>
      <span><span class="brand-name">Global Scale</span><br><span class="brand-sub">Banca Internacional</span></span></a>
    <div class="reg-hero-body">
      <div>
        <h1>Abra a sua conta<br>em três passos.</h1>
        <p>Escolha a região onde ficam os seus dados e a moeda da conta. Pode transferir entre as três regiões com câmbio transparente.</p>
      </div>
      <div class="reg-block">
        <span class="reg-kicker">Três regiões, três moedas</span>
        <div class="reg-regions">
          ${REGION_CODES.map((r) => `
            <div class="reg-region" data-region-card="${r}">
              <span class="reg-code">${r}</span>
              <span class="grow"><b>${esc(REGIONS[r].name)} · ${esc(REGIONS[r].city)}</b><span>Contas GS-${r} · ${esc(CURRENCY_NAMES[REGIONS[r].currency])}</span></span>
              <span class="reg-cur">${esc(REGIONS[r].currency)}</span>
            </div>`).join("")}
        </div>
      </div>
      <div class="reg-block">
        <span class="reg-kicker">Do pedido à conta ativa</span>
        <ol class="reg-flow">
          <li><span class="dot">1</span><span><b>Registo</b>Preenche os seus dados (cerca de 2 minutos).</span></li>
          <li><span class="dot">2</span><span><b>Verificação KYC</b>Um operador confirma a sua identidade.</span></li>
          <li><span class="dot">3</span><span><b>Conta ativa</b>A conta é aberta na região escolhida e pode entrar.</span></li>
        </ol>
      </div>
    </div>
    <p class="hero-foot">${icon("lock")} Documento e data de nascimento guardados cifrados (AES-256). Plataforma de demonstração académica (ISUTC): não utilize dados reais.</p>
  </section>`;
}

function stepper(current, done = false) {
  return `<ol class="stepper" aria-label="Progresso do registo">${STEPS.map(([t, s], i) => {
    const n = i + 1;
    const state = done || n < current ? "done" : n === current ? "current" : "";
    return `<li class="${state}" ${n === current && !done ? 'aria-current="step"' : ""}>
      <span class="s-dot">${state === "done" ? icon("check") : n}</span><span class="s-text"><b>${t}</b><span>${s}</span></span></li>`;
  }).join("")}</ol>`;
}

export async function render({ root }) {
  const maxBirth = new Date();
  maxBirth.setFullYear(maxBirth.getFullYear() - 18);
  const data = { region: "EU" };
  let step = 1;

  root.innerHTML = `
  <div class="auth">
    ${regHero()}
    <section class="auth-panel">
      <form class="auth-form reg-form" id="reg" novalidate>
        <a href="#/login" class="hint back-link">${icon("chevronLeft")} Voltar à entrada</a>
        <h2>Abrir conta</h2>
        <p>A sua identidade é verificada por um operador antes de a conta ficar ativa.</p>
        <div id="stepper">${stepper(1)}</div>

        <fieldset class="step" data-step="1">
          <legend>Dados pessoais</legend>
          <div class="field"><label for="full_name">Nome completo</label>
            <input class="input" id="full_name" autocomplete="name" placeholder="Como consta no documento" required></div>
          <div class="field"><label for="email">Email</label>
            <input class="input" id="email" type="email" autocomplete="email" placeholder="nome@exemplo.com" required>
            <p class="hint">É com este email que vai entrar.</p></div>
          <div class="grid g-2" style="gap:14px">
            <div class="field"><label for="document_id">Documento de identificação</label>
              <input class="input" id="document_id" placeholder="N.º do CC ou passaporte" required></div>
            <div class="field"><label for="birth_date">Data de nascimento</label>
              <input class="input num" id="birth_date" inputmode="numeric" autocomplete="bday" placeholder="dd/mm/aaaa" maxlength="10" required></div>
          </div>
        </fieldset>

        <fieldset class="step" data-step="2" hidden>
          <legend>Região e moeda</legend>
          <div class="field">
            <span class="label">Onde fica a sua conta</span>
            <div class="region-choices" role="radiogroup" aria-label="Região">
              ${REGION_CODES.map((r) => `
                <button type="button" class="choice region-choice" role="radio" aria-checked="${r === data.region}" data-region="${r}">
                  <span class="cur-badge">${esc(REGIONS[r].currency)}</span>
                  <span class="grow"><b>${esc(REGIONS[r].name)}</b><span>${esc(REGIONS[r].city)} · conta em ${esc(PLURAL[REGIONS[r].currency])}</span></span>
                </button>`).join("")}
            </div>
            <p class="hint" id="region-hint"></p>
          </div>
          <div class="field"><label for="phone">Telemóvel</label>
            <div class="phone-input"><span class="phone-code" id="phone-code"></span>
              <input class="input" id="phone" type="tel" autocomplete="tel-national" inputmode="tel" required></div>
            <p class="hint" id="phone-hint"></p></div>
        </fieldset>

        <fieldset class="step" data-step="3" hidden>
          <legend>Segurança</legend>
          <div class="field"><label for="password">Palavra-passe</label>
            <div class="input-affix">
              <input class="input" id="password" type="password" autocomplete="new-password" required style="padding-right:48px">
              <button type="button" class="btn btn-ghost btn-sm pw-toggle" id="toggle-pw" aria-label="Mostrar palavra-passe">${icon("eye")}</button>
            </div>
            <div class="row wrap" id="pw-rules" style="gap:6px;margin-top:8px">${RULES.map(([, t], i) => `<span class="chip" data-rule="${i}">${icon("check")}${esc(t)}</span>`).join("")}</div>
          </div>
          <div class="field"><label for="password2">Confirmar palavra-passe</label>
            <input class="input" id="password2" type="password" autocomplete="new-password" required></div>
          <div class="review" id="review"></div>
        </fieldset>

        <div id="form-error"></div>
        <div class="step-actions">
          <button type="button" class="btn btn-secondary btn-lg" id="back" hidden>${icon("chevronLeft")} Anterior</button>
          <button class="btn btn-primary btn-lg" id="next" type="submit">Continuar ${icon("arrowRight")}</button>
        </div>
      </form>
    </section>
  </div>`;

  const f = (id) => $(`#${id}`, root);

  // --- data de nascimento: dd/mm/aaaa com as barras inseridas enquanto escreve ---
  f("birth_date").addEventListener("input", (e) => {
    const digits = e.target.value.replace(/\D/g, "").slice(0, 8);
    e.target.value = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean).join("/");
  });

  // --- região: cartões, indicativo do telemóvel e painel lateral acompanham a escolha ---
  function applyRegion() {
    const r = data.region, p = PHONE[r];
    $$("[data-region]", root).forEach((x) => x.setAttribute("aria-checked", String(x.dataset.region === r)));
    $$("[data-region-card]", root).forEach((x) => x.classList.toggle("active", x.dataset.regionCard === r));
    f("phone-code").textContent = p.code;
    f("phone").placeholder = p.example;
    f("phone-hint").textContent = `Indicativo de ${p.country} (${p.code}). Se tiver um número de outro país, escreva-o com o indicativo, ex.: +44…`;
    f("region-hint").innerHTML = `${icon("info")} Conta <b>GS-${r}</b> em ${esc(CURRENCY_NAMES[REGIONS[r].currency])} (${esc(REGIONS[r].currency)}), com os dados guardados no centro de dados de ${esc(REGIONS[r].city)}.`;
  }
  $$("[data-region]", root).forEach((b) => b.addEventListener("click", () => { data.region = b.dataset.region; applyRegion(); }));
  applyRegion();

  // --- palavra-passe: regras em tempo real ---
  const pw = f("password");
  pw.addEventListener("input", () => RULES.forEach(([re], i) => {
    $(`[data-rule="${i}"]`, root).className = `chip ${re.test(pw.value) ? "status-done" : ""}`;
  }));
  f("toggle-pw").addEventListener("click", () => { const t = pw.type === "password" ? "text" : "password"; pw.type = t; f("password2").type = t; });

  function phoneValue() {
    const raw = f("phone").value.replace(/[\s().-]/g, "");
    if (!raw) return "";
    return raw.startsWith("+") ? raw : `${PHONE[data.region].code}${raw.replace(/^0+/, "")}`;
  }

  function validate(n) {
    let ok = true;
    const check = (id, cond, msg) => { fieldError(f(id), cond ? null : msg); ok &&= cond; };
    if (n === 1) {
      check("full_name", f("full_name").value.trim().length >= 3, "Indique o nome completo");
      check("email", /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(f("email").value.trim()), "Email inválido");
      check("document_id", f("document_id").value.trim().length >= 5, "Documento inválido");
      const birth = parseDate(f("birth_date").value);
      check("birth_date", !!birth && birth <= maxBirth, birth ? "Tem de ter pelo menos 18 anos" : "Use o formato dd/mm/aaaa");
    }
    if (n === 2) check("phone", /^\+[0-9]{9,15}$/.test(phoneValue()), "Telemóvel inválido");
    if (n === 3) {
      check("password", RULES.every(([re]) => re.test(pw.value)), "A palavra-passe não cumpre os requisitos");
      check("password2", f("password2").value === pw.value && !!pw.value, "As palavras-passe não coincidem");
    }
    return ok;
  }

  function review() {
    const r = data.region;
    f("review").innerHTML = `
      <div class="review-head"><b>Confirme os seus dados</b><button type="button" class="link-btn" data-goto="1">Alterar</button></div>
      <dl class="kv">
        <dt>Nome</dt><dd>${esc(f("full_name").value.trim())}</dd>
        <dt>Email</dt><dd>${esc(f("email").value.trim())}</dd>
        <dt>Telemóvel</dt><dd class="num">${esc(phoneValue())}</dd>
        <dt>Documento</dt><dd>${esc(f("document_id").value.trim())}</dd>
        <dt>Nascimento</dt><dd class="num">${esc(f("birth_date").value)}</dd>
        <dt>Conta</dt><dd>${esc(regionName(r))} · ${esc(REGIONS[r].city)} · ${esc(REGIONS[r].currency)}</dd>
      </dl>`;
    $("[data-goto]", f("review")).addEventListener("click", () => go(1));
  }

  function go(n) {
    step = n;
    $$(".step", root).forEach((s) => { s.hidden = Number(s.dataset.step) !== n; });
    f("stepper").innerHTML = stepper(n);
    f("back").hidden = n === 1;
    f("next").innerHTML = n === 3 ? `${icon("check")} Submeter pedido` : `Continuar ${icon("arrowRight")}`;
    f("form-error").innerHTML = "";
    if (n === 3) review();
    setTimeout(() => $(`.step[data-step="${n}"] input`, root)?.focus(), 30);
  }
  f("back").addEventListener("click", () => go(step - 1));

  f("reg").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!validate(step)) return;
    if (step < 3) return go(step + 1);

    const birth = parseDate(f("birth_date").value);
    const body = {
      full_name: f("full_name").value.trim(), email: f("email").value.trim(), phone: phoneValue(),
      password: pw.value, region: data.region, document_id: f("document_id").value.trim(),
      birth_date: birth.toISOString().slice(0, 10),
    };
    const btn = f("next");
    busy(btn, true, "A submeter…");
    try {
      const r = await api("/auth/register", { method: "POST", body, auth: false });
      confirmation(r, body);
    } catch (ex) {
      busy(btn, false);
      f("form-error").innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.status === 409 ? "Já existe uma conta com este email ou telemóvel." : ex.message)}</span></div>`;
    }
  });

  function confirmation(r, body) {
    const reg = REGIONS[body.region];
    f("reg").outerHTML = `
      <div class="auth-form reg-form reg-done">
        ${stepper(3, true)}
        <div class="receipt-icon pending">${icon("clock")}</div>
        <h2 style="text-align:center">Pedido recebido</h2>
        <p style="text-align:center">Obrigado, ${esc(body.full_name.split(" ")[0])}. O seu pedido aguarda a verificação de identidade por um operador.</p>
        <div class="panel" style="margin-top:20px"><div class="panel-body">
          <dl class="kv">
            <dt>Referência</dt><dd class="mono">${esc(r.id.slice(0, 8).toUpperCase())}</dd>
            <dt>Estado</dt><dd><span class="chip status-pending">${icon("clock")}A aguardar verificação</span></dd>
            <dt>Conta a abrir</dt><dd>GS-${esc(body.region)} · ${esc(reg.currency)} · ${esc(reg.city)}</dd>
          </dl>
        </div></div>
        <div class="section-title" style="margin-top:22px">O que acontece a seguir</div>
        <ol class="next-steps">
          <li class="done"><span class="dot">${icon("check")}</span><span><b>Pedido registado</b>Os seus dados ficaram guardados de forma cifrada.</span></li>
          <li class="current"><span class="dot">2</span><span><b>Verificação de identidade</b>Um operador confirma o documento e os dados que indicou.</span></li>
          <li><span class="dot">3</span><span><b>Conta aberta em ${esc(PLURAL[reg.currency])}</b>No centro de dados de ${esc(reg.city)}. Depois entra com ${esc(body.email)} e a sua palavra-passe.</span></li>
        </ol>
        <div class="banner banner-info" style="margin-top:18px">${icon("info")}<span>Guarde a referência. Se tentar entrar antes da aprovação, verá a indicação de que a conta ainda não está ativa: basta aguardar e voltar a tentar.</span></div>
        <a class="btn btn-primary btn-block btn-lg" href="#/login" style="margin-top:20px">Ir para a entrada</a>
      </div>`;
  }
}
