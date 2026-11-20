import { api, logout, session } from "../api.js";
import { dateTime, initials, REGIONS, roleLabel } from "../format.js";
import { icon } from "../icons.js";
import { prefs } from "../store.js";
import { $, $$, esc, toast } from "../ui.js";
import { pageHead } from "./common.js";

export async function render({ root, claims, navigate }) {
  const s = session.get();
  const jwks = await api("/.well-known/jwks.json", { auth: false }).catch(() => null);
  const minutes = Math.max(0, Math.round((claims.exp * 1000 - Date.now()) / 60000));
  const name = s.profile?.name || roleLabel(claims.role);
  const sec = (title, text, content) => `<div class="form-section"><div class="fs-intro"><h3>${title}</h3><p>${text}</p></div><div>${content}</div></div>`;
  root.innerHTML = `
    ${pageHead("Definições", "Perfil, sessão, aparência e segurança da sua conta.")}
    <div class="bento">
      <section class="panel c-8"><div class="panel-body" style="padding-top:22px">
        ${sec("Perfil", "Dados de identificação associados à sua conta.", `
          <div class="row" style="gap:16px;margin-bottom:16px"><span class="avatar" style="width:56px;height:56px;font-size:1.1rem">${esc(initials(name))}</span>
            <div><h2 style="font-size:1.2rem">${esc(name)}</h2><p class="soft">${esc(s.profile?.email || "")}</p></div></div>
          <div class="form-grid">
            <div class="field"><label>Perfil</label><input class="input" value="${esc(roleLabel(claims.role))}" readonly></div>
            <div class="field"><label>Região</label><input class="input" value="${esc(claims.region ? `${REGIONS[claims.region]?.name} · ${REGIONS[claims.region]?.city}` : "Global (back-office)")}" readonly></div>
            <div class="field full"><label>Identificador</label><input class="input mono" value="${esc(claims.sub)}" readonly></div>
          </div>`)}
        ${sec("Sessão", "A credencial é renovada automaticamente enquanto estiver ativo.", `
          <dl class="kv">
            <dt>Início da sessão</dt><dd>${esc(dateTime(claims.iat * 1000))}</dd>
            <dt>Credencial válida por</dt><dd>${minutes} min · renovada automaticamente</dd>
            <dt>Emitida por</dt><dd class="mono">${esc(claims.iss)}</dd>
            <dt>Assinatura</dt><dd>RS256 · chave <span class="mono">${esc((jwks?.keys?.[0]?.kid || "").slice(0, 10))}…</span></dd>
          </dl>
          <button class="btn btn-secondary" id="end" style="margin-top:16px">${icon("logout")} Terminar sessão</button>`)}
        ${sec("Aparência", "Escolha o tema e a forma como os saldos são apresentados.", `
          <div class="segmented" role="group" aria-label="Tema">
            ${[["auto", "Automático"], ["light", "Claro"], ["dark", "Escuro"]].map(([k, l]) => `<button data-theme-opt="${k}" aria-pressed="${prefs.theme === k}">${l}</button>`).join("")}
          </div>
          <label class="row" style="gap:10px;margin-top:18px;font-size:.9rem"><input type="checkbox" id="hide" ${prefs.hideBalances ? "checked" : ""} style="width:18px;height:18px;accent-color:var(--accent)"> Ocultar saldos por omissão</label>`)}
      </div></section>
      <section class="panel c-4">
        <div class="panel-head"><h3>Como protegemos a sua conta</h3></div>
        <ul class="list">
          ${[["lock", "Ligações cifradas", "TLS em todos os pedidos, do seu browser às bases de dados."],
             ["key", "Palavra-passe irreversível", "Guardamos apenas um resumo Argon2; 5 tentativas falhadas bloqueiam o acesso 15 min."],
             ["fingerprint", "Ordens assinadas", "Cada transferência é assinada digitalmente (Ed25519) e verificada antes de executar."],
             ["shield", "Dados pessoais cifrados", "Documento e data de nascimento guardados com AES-256-GCM."],
             ["doc", "Registo imutável", "Todas as operações ficam num registo de auditoria encadeado por hash."]]
            .map(([i, t, d]) => `<li class="list-item"><span class="tx-icon">${icon(i)}</span><span class="grow"><span class="title">${t}</span><span class="sub" style="white-space:normal">${d}</span></span></li>`).join("")}
        </ul>
      </section>
    </div>`;

  $$("[data-theme-opt]", root).forEach((b) => b.addEventListener("click", () => {
    prefs.theme = b.dataset.themeOpt;
    $$("[data-theme-opt]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  $("#hide", root).addEventListener("change", (e) => { prefs.hideBalances = e.target.checked; });
  $("#end", root).addEventListener("click", async () => { await logout(); toast("Sessão terminada", "info"); navigate("/login"); });
}
