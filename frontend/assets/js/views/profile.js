import { api, logout, session } from "../api.js";
import { dateTime, REGIONS, roleLabel } from "../format.js";
import { icon } from "../icons.js";
import { prefs } from "../store.js";
import { $, $$, esc, toast } from "../ui.js";
import { pageHead } from "./common.js";

export async function render({ root, claims, navigate }) {
  const s = session.get();
  const jwks = await api("/.well-known/jwks.json", { auth: false }).catch(() => null);
  const minutes = Math.max(0, Math.round((claims.exp * 1000 - Date.now()) / 60000));
  root.innerHTML = `
    ${pageHead("Perfil e segurança")}
    <div class="grid g-2">
      <section class="card card-pad">
        <div class="row" style="gap:16px"><span class="avatar" style="width:56px;height:56px;font-size:1.1rem">${esc((s.profile?.name || "?").split(" ").map((p) => p[0]).slice(0, 2).join(""))}</span>
          <div><h2>${esc(s.profile?.name || "")}</h2><p class="soft">${esc(s.profile?.email || "")}</p></div></div>
        <dl class="kv" style="margin-top:18px">
          <dt>Perfil</dt><dd>${esc(roleLabel(claims.role))}</dd>
          ${claims.region ? `<dt>Região</dt><dd>${esc(REGIONS[claims.region]?.name)} · ${esc(REGIONS[claims.region]?.city)}</dd>` : ""}
          <dt>Identificador</dt><dd class="mono">${esc(claims.sub)}</dd>
        </dl>
      </section>
      <section class="card card-pad">
        <h3>Sessão</h3>
        <dl class="kv" style="margin-top:8px">
          <dt>Início da sessão</dt><dd>${esc(dateTime(claims.iat * 1000))}</dd>
          <dt>Credencial válida por</dt><dd>${minutes} min · renovada automaticamente</dd>
          <dt>Emitida por</dt><dd class="mono">${esc(claims.iss)}</dd>
          <dt>Assinatura</dt><dd>RS256 · chave <span class="mono">${esc((jwks?.keys?.[0]?.kid || "").slice(0, 10))}…</span></dd>
        </dl>
        <button class="btn btn-secondary btn-block" id="end" style="margin-top:18px">${icon("logout")} Terminar sessão</button>
      </section>
      <section class="card card-pad">
        <h3>Aparência</h3>
        <div class="segmented" role="group" aria-label="Tema" style="margin-top:14px">
          ${[["auto", "Automático"], ["light", "Claro"], ["dark", "Escuro"]].map(([k, l]) => `<button data-theme-opt="${k}" aria-pressed="${prefs.theme === k}">${l}</button>`).join("")}
        </div>
        <label class="row" style="gap:10px;margin-top:18px;font-size:.9rem"><input type="checkbox" id="hide" ${prefs.hideBalances ? "checked" : ""} style="width:18px;height:18px;accent-color:var(--accent)"> Ocultar saldos por omissão</label>
      </section>
      <section class="card card-pad">
        <h3>Como protegemos a sua conta</h3>
        <ul class="list" style="margin:8px -24px -10px">
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
