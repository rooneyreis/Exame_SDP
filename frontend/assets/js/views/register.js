import { api } from "../api.js";
import { icon } from "../icons.js";
import { $, $$, busy, esc, fieldError } from "../ui.js";
import { authHero } from "./login.js";

const RULES = [
  [/.{8,}/, "8 ou mais caracteres"],
  [/[A-Z]/, "Uma letra maiúscula"],
  [/[0-9]/, "Um número"],
  [/[^A-Za-z0-9]/, "Um símbolo"],
];

export async function render({ root }) {
  const maxBirth = new Date();
  maxBirth.setFullYear(maxBirth.getFullYear() - 18);
  root.innerHTML = `
  <div class="auth">
    ${authHero()}
    <section class="auth-panel">
      <form class="auth-form" id="reg" novalidate style="max-width:460px">
        <a href="#/login" class="hint" style="display:inline-flex;gap:4px;align-items:center">${icon("chevronLeft")} Voltar</a>
        <h2 style="margin-top:14px">Abrir conta</h2>
        <p>Demora cerca de 2 minutos. A sua identidade é verificada por um operador antes da ativação.</p>
        <div class="stack" style="gap:16px">
          <div class="field"><label for="full_name">Nome completo</label>
            <input class="input" id="full_name" autocomplete="name" placeholder="Como consta no documento" required></div>
          <div class="grid g-2" style="gap:14px">
            <div class="field"><label for="email">Email</label><input class="input" id="email" type="email" autocomplete="email" required></div>
            <div class="field"><label for="phone">Telemóvel</label><input class="input" id="phone" type="tel" autocomplete="tel" placeholder="+351 912 345 678" required></div>
          </div>
          <div class="field">
            <span class="label">Região da conta</span>
            <div class="choice-grid" role="radiogroup" aria-label="Região">
              <button type="button" class="choice" role="radio" aria-checked="true" data-region="EU">${icon("globe")}<span class="grow"><b>Europa</b><span>Conta em EUR · Lisboa</span></span></button>
              <button type="button" class="choice" role="radio" aria-checked="false" data-region="AM">${icon("globe")}<span class="grow"><b>América</b><span>Conta em USD · Nova Iorque</span></span></button>
            </div>
            <p class="hint">Os seus dados ficam guardados no centro de dados da região escolhida.</p>
          </div>
          <div class="grid g-2" style="gap:14px">
            <div class="field"><label for="document_id">Documento de identificação</label><input class="input" id="document_id" placeholder="N.º do CC ou passaporte" required></div>
            <div class="field"><label for="birth_date">Data de nascimento</label><input class="input" id="birth_date" type="date" max="${maxBirth.toISOString().slice(0, 10)}" required></div>
          </div>
          <div class="field"><label for="password">Palavra-passe</label>
            <input class="input" id="password" type="password" autocomplete="new-password" required>
            <div class="row wrap" id="pw-rules" style="gap:6px">${RULES.map(([, t], i) => `<span class="chip" data-rule="${i}">${icon("check")}${esc(t)}</span>`).join("")}</div>
          </div>
          <div id="form-error"></div>
          <button class="btn btn-primary btn-lg btn-block" id="submit" type="submit">Submeter pedido</button>
          <p class="hint" style="display:flex;gap:8px">${icon("lock")}<span>O documento e a data de nascimento são guardados cifrados (AES-256). A palavra-passe nunca é guardada: só uma impressão digital irreversível (Argon2).</span></p>
        </div>
      </form>
    </section>
  </div>`;

  let region = "EU";
  $$("[data-region]", root).forEach((b) => b.addEventListener("click", () => {
    region = b.dataset.region;
    $$("[data-region]", root).forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  }));
  const pw = $("#password", root);
  pw.addEventListener("input", () => {
    RULES.forEach(([re], i) => {
      const chip = $(`[data-rule="${i}"]`, root);
      chip.className = `chip ${re.test(pw.value) ? "status-done" : ""}`;
    });
  });

  $("#reg", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = (id) => $(`#${id}`, root);
    const body = {
      full_name: f("full_name").value.trim(), email: f("email").value.trim(), phone: f("phone").value.replace(/\s+/g, ""),
      password: pw.value, region, document_id: f("document_id").value.trim(), birth_date: f("birth_date").value,
    };
    let ok = true;
    const check = (id, cond, msg) => { fieldError(f(id), cond ? null : msg); ok &&= cond; };
    check("full_name", body.full_name.length >= 3, "Indique o nome completo");
    check("email", /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(body.email), "Email inválido");
    check("phone", /^\+?[0-9]{9,15}$/.test(body.phone), "Telemóvel inválido (9 a 15 dígitos)");
    check("document_id", body.document_id.length >= 5, "Documento inválido");
    check("birth_date", !!body.birth_date && new Date(body.birth_date) <= maxBirth, "Tem de ter pelo menos 18 anos");
    check("password", RULES.every(([re]) => re.test(body.password)), "A palavra-passe não cumpre os requisitos");
    if (!ok) return;

    const btn = f("submit");
    busy(btn, true, "A submeter…");
    try {
      const r = await api("/auth/register", { method: "POST", body, auth: false });
      root.querySelector(".auth-form").innerHTML = `
        <div class="receipt-icon pending">${icon("clock")}</div>
        <h2 style="text-align:center">Pedido recebido</h2>
        <p style="text-align:center">Obrigado, ${esc(body.full_name.split(" ")[0])}. A sua identidade será verificada por um operador. Após a aprovação, a sua conta em ${region === "EU" ? "euros" : "dólares"} é aberta automaticamente e pode entrar com o seu email.</p>
        <div class="card card-pad" style="margin-top:20px"><dl class="kv">
          <dt>Referência do pedido</dt><dd class="mono">${esc(r.id.slice(0, 8).toUpperCase())}</dd>
          <dt>Estado</dt><dd><span class="chip status-pending">${icon("clock")}A aguardar verificação</span></dd>
          <dt>Região</dt><dd>${region === "EU" ? "Europa" : "América"}</dd>
        </dl></div>
        <a class="btn btn-secondary btn-block btn-lg" href="#/login" style="margin-top:20px">Voltar ao início</a>`;
    } catch (ex) {
      busy(btn, false);
      $("#form-error", root).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.status === 409 ? "Já existe uma conta com este email ou telemóvel." : ex.message)}</span></div>`;
    }
  });
}
