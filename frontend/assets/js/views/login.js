import { login, session } from "../api.js";
import { icon, LOGO } from "../icons.js";
import { $, $$, busy, esc, fieldError } from "../ui.js";

const DEMO = [
  ["ana.silva@cliente.test", "Cliente#2026", "Ana Silva", "Cliente · Europa"],
  ["david.smith@cliente.test", "Cliente#2026", "David Smith", "Cliente · América"],
  ["amina.mussa@cliente.test", "Cliente#2026", "Amina Mussa", "Cliente · África"],
  ["operador@globalscale.test", "Staff#2026", "Operador", "Back-office"],
  ["auditor@globalscale.test", "Staff#2026", "Auditor", "Conformidade"],
  ["admin@globalscale.test", "Staff#2026", "Administrador", "Infraestrutura"],
  ["bruno.costa@cliente.test", "Cliente#2026", "Bruno Costa", "Cliente · Europa"],
];

export function prettyName(email) {
  const local = (email || "").split("@")[0];
  if (!local.includes(".")) return local.charAt(0).toUpperCase() + local.slice(1);
  return local.split(/[._-]/).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

export function authHero() {
  return `
  <section class="auth-hero">
    <a class="brand" href="#/login"><span class="brand-mark">${LOGO}</span>
      <span><span class="brand-name">Global Scale</span><br><span class="brand-sub">Banca Internacional</span></span></a>
    <div class="hero-copy">
      <h1>O seu dinheiro,<br>sem fronteiras.</h1>
      <p>Contas na Europa, na América e em África, transferências nacionais e internacionais com câmbio transparente, e cada operação confirmada de ponta a ponta.</p>
    </div>
    <div class="hero-points">
      <div class="hero-point">${icon("lock")}<b>Cifrado de ponta a ponta</b><span>TLS em todas as ligações</span></div>
      <div class="hero-point">${icon("shield")}<b>Operações garantidas</b><span>Nunca sai sem chegar</span></div>
      <div class="hero-point">${icon("globe")}<b>Duas regiões</b><span>Lisboa · Nova Iorque</span></div>
    </div>
    <p class="hero-foot">Global Scale Corporation · Plataforma de demonstração académica (ISUTC). Não utilize dados reais.</p>
  </section>`;
}

export async function render({ root, navigate }) {
  const expired = !session.get();
  root.innerHTML = `
  <div class="auth">
    ${authHero()}
    <section class="auth-panel">
      <form class="auth-form" id="login" novalidate>
        <h2>Bem-vindo de volta</h2>
        <p>Entre na sua conta para gerir o seu dinheiro.</p>
        <div class="stack" style="gap:16px">
          <div class="field">
            <label for="email">Email</label>
            <input class="input" id="email" type="email" autocomplete="username" inputmode="email" placeholder="nome@exemplo.com" required>
          </div>
          <div class="field">
            <label for="password">Palavra-passe</label>
            <div class="input-affix">
              <input class="input" id="password" type="password" autocomplete="current-password" placeholder="••••••••" required style="padding-right:48px">
              <button type="button" class="btn btn-ghost btn-sm" id="toggle-pw" style="position:absolute;right:6px;top:7px" aria-label="Mostrar palavra-passe">${icon("eye")}</button>
            </div>
          </div>
          <div id="form-error"></div>
          <button class="btn btn-primary btn-lg btn-block" id="submit" type="submit">Entrar</button>
          <p class="hint" style="text-align:center">Ainda não é cliente? <a href="#/register">Abrir conta</a></p>
        </div>
        <details class="demo-box">
          <summary>${icon("info")} Acessos de demonstração</summary>
          <div class="demo-users">
            ${DEMO.map(([e, p, n, r]) => `<button type="button" data-email="${esc(e)}" data-pw="${esc(p)}"><b>${esc(n)}</b>${esc(r)}</button>`).join("")}
          </div>
        </details>
        <p class="hint" style="margin-top:20px;display:flex;gap:8px;align-items:flex-start">${icon("lock")}
          <span>Nunca lhe pediremos a palavra-passe por email ou telefone. Após 5 tentativas falhadas, o acesso fica bloqueado durante 15 minutos.</span></p>
      </form>
    </section>
  </div>`;

  const form = $("#login", root);
  const email = $("#email", root), pw = $("#password", root), btn = $("#submit", root);
  setTimeout(() => email.focus(), 50);

  $("#toggle-pw", root).addEventListener("click", () => { pw.type = pw.type === "password" ? "text" : "password"; });
  $$("[data-email]", root).forEach((b) => b.addEventListener("click", () => {
    email.value = b.dataset.email; pw.value = b.dataset.pw; btn.focus();
  }));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#form-error", root);
    err.innerHTML = "";
    fieldError(email, email.value.includes("@") ? null : "Indique um email válido");
    fieldError(pw, pw.value ? null : "Indique a palavra-passe");
    if (!email.value.includes("@") || !pw.value) return;
    busy(btn, true, "A verificar…");
    try {
      const s = await login(email.value.trim().toLowerCase(), pw.value);
      session.set({ access_token: s.access, refresh_token: s.refresh }, { email: email.value.trim().toLowerCase(), name: prettyName(email.value.trim()) });
      const next = sessionStorage.getItem("gs.next");
      sessionStorage.removeItem("gs.next");
      navigate(next && next !== "/login" ? next : "/");
    } catch (ex) {
      busy(btn, false);
      const map = {
        401: "Email ou palavra-passe incorretos.",
        403: ex.message.includes("PENDENTE") ? "A sua conta aguarda verificação de identidade (KYC). Será notificado quando for aprovada." : ex.message,
        423: "Por segurança, o acesso está temporariamente bloqueado. Tente novamente dentro de 15 minutos.",
      };
      err.innerHTML = `<div class="banner ${ex.status === 423 ? "banner-warn" : "banner-bad"}">${icon(ex.status === 403 ? "clock" : "alert")}<span>${esc(map[ex.status] || ex.message)}</span></div>`;
    }
  });
  void expired;
}
