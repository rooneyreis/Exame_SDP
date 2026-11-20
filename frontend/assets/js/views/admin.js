import { api } from "../api.js";
import { dateTime, initials, roleLabel } from "../format.js";
import { icon } from "../icons.js";
import { $, $$, busy, esc, fieldError, toast } from "../ui.js";
import { pageHead } from "./common.js";

export async function render(ctx) {
  if (ctx.path === "/admin/staff") return staff(ctx);
  return infra(ctx);
}

const SERVICE_INFO = {
  auth: ["key", "Autenticação", "Emissão de credenciais"], coordinator: ["transfer", "Coordenador", "Transações entre regiões"],
  "legacy-bank": ["bank", "Banco correspondente", "Liquidação (XML)"], "api-1": ["server", "API · nó 1", "Pedidos de clientes"],
  "api-2": ["server", "API · nó 2", "Pedidos de clientes"],
};
const DB_INFO = {
  "pg-core": "Identidades e registo de transações", "pg-europa": "Contas Europa", "pg-europa-replica": "Contas Europa (réplica)",
  "pg-america": "Contas América", "pg-america-replica": "Contas América (réplica)",
};

async function infra({ root }) {
  async function draw() {
    const s = await api("/admin/status");
    root.innerHTML = `
      ${pageHead("Infraestrutura", `Estado de todos os nós, visto a partir de <b>${esc(s.served_by)}</b>.`,
        `<button class="btn btn-secondary" id="refresh">${icon("refresh")} Atualizar</button>`)}
      <div class="banner ${s.all_up ? "banner-good" : "banner-warn"}" style="margin-bottom:20px">${icon(s.all_up ? "check" : "alert")}
        <span><b>${s.all_up ? "Todos os sistemas operacionais" : "Serviço degradado"}</b> · ${Object.values(s.services).filter((v) => v.up).length + Object.values(s.databases).filter((v) => v.up).length} de ${Object.keys(s.services).length + Object.keys(s.databases).length} nós disponíveis</span></div>
      <div class="grid g-2">
        <section class="card card-pad"><h3>Serviços</h3><div class="stack" style="gap:10px;margin-top:14px">
          ${Object.entries(s.services).map(([n, v]) => { const [ic, label, sub] = SERVICE_INFO[n] || ["server", n, ""]; return `
            <div class="node"><span class="pulse ${v.up ? "" : "down"}"></span><span class="tx-icon">${icon(ic)}</span>
              <span class="grow"><b>${esc(label)}</b><div class="sub">${esc(sub)} · <span class="mono">${esc(n)}</span></div></span>
              <span class="hint num">${v.self ? "este nó" : v.up ? `${v.ms} ms` : esc(v.error || "em baixo")}</span></div>`; }).join("")}
        </div></section>
        <section class="card card-pad"><h3>Bases de dados</h3><div class="stack" style="gap:10px;margin-top:14px">
          ${Object.entries(s.databases).map(([n, v]) => `
            <div class="node"><span class="pulse ${v.up ? "" : "down"}"></span><span class="tx-icon">${icon("database")}</span>
              <span class="grow"><b>${esc(DB_INFO[n] || n)}</b><div class="sub mono">${esc(n)}</div></span>
              ${v.up ? `<span class="chip ${v.role === "primário" ? "chip-accent" : ""}">${esc(v.role)}</span>` : `<span class="chip status-failed">em baixo</span>`}</div>`).join("")}
        </div>
        <p class="hint" style="margin-top:12px">${icon("lock")} Todas as ligações às bases de dados exigem TLS com verificação do certificado.</p></section>
      </div>
      <section class="card card-pad" style="margin-top:20px">
        <div class="row between wrap"><div><h3>Simulação de falhas</h3><p class="hint">Para demonstração: provoca falhas controladas no coordenador. Desliga-se sozinho se o coordenador reiniciar.</p></div>
          <button class="btn btn-secondary btn-sm" data-chaos='{"off":true}'>${icon("check")} Desligar tudo</button></div>
        <div class="choice-grid" style="margin-top:14px">
          ${[["Pausa de 20 s após reservar", '{"pause_after_prepare":20}', "clock"],
             ["Falha na Europa", '{"fail_participant":"EU"}', "x"],
             ["Falha na América", '{"fail_participant":"AM"}', "x"],
             ["Crash antes da decisão", '{"crash_after_prepare":true}', "bolt"],
             ["Crash após a decisão", '{"crash_after_decision":true}', "bolt"]]
            .map(([l, m, i]) => `<button class="choice" data-chaos='${m}'>${icon(i)}<span class="grow"><b>${l}</b><span class="mono">${esc(m)}</span></span></button>`).join("")}
        </div>
        <p class="hint" id="chaos-state" style="margin-top:12px"></p>
      </section>
      <p class="hint" style="margin-top:16px">Sistema de ficheiros distribuído: ${s.nfs.up ? `montado em <span class="mono">${esc(s.nfs.mount)}</span> · dias com registos: ${esc(s.nfs.days.join(", "))}` : "indisponível"}</p>`;
    $("#refresh", root).addEventListener("click", draw);
    $$("[data-chaos]", root).forEach((b) => b.addEventListener("click", async () => {
      busy(b, true);
      try {
        const r = await api("/admin/chaos", { method: "POST", body: JSON.parse(b.dataset.chaos) });
        const on = Object.entries(r).filter(([, v]) => v && v !== 0).map(([k, v]) => `${k}=${v}`);
        $("#chaos-state", root).textContent = on.length ? `Ativo: ${on.join(", ")}` : "Nenhuma falha ativa.";
        toast(on.length ? "Simulação ativada" : "Simulações desligadas", "info");
      } catch (ex) { toast(ex.message, "bad"); }
      busy(b, false);
    }));
  }
  await draw();
}

async function staff({ root }) {
  async function draw() {
    const users = (await api("/admin/users")).filter((u) => u.role !== "cliente");
    root.innerHTML = `
      ${pageHead("Equipa", "Operadores, auditores e administradores com acesso ao back-office.")}
      <div class="grid g-main">
        <section class="card"><ul class="list">${users.map((u) => `
          <li class="list-item"><span class="avatar">${esc(initials(u.full_name))}</span>
            <span class="grow"><span class="title">${esc(u.full_name)}</span><span class="sub">${esc(u.email)} · desde ${esc(dateTime(u.created_at))}</span></span>
            <span class="chip">${esc(roleLabel(u.role))}</span></li>`).join("")}</ul></section>
        <form class="card card-pad" id="new" novalidate>
          <h3>Adicionar membro</h3>
          <div class="stack" style="gap:12px;margin-top:14px">
            <div class="field"><label for="s-name">Nome</label><input class="input" id="s-name"></div>
            <div class="field"><label for="s-email">Email</label><input class="input" id="s-email" type="email"></div>
            <div class="field"><label for="s-phone">Telemóvel</label><input class="input" id="s-phone" type="tel"></div>
            <div class="field"><label for="s-role">Função</label><select class="select" id="s-role"><option value="operador">Operador</option><option value="auditor">Auditor</option><option value="admin">Administrador</option></select></div>
            <div class="field"><label for="s-pw">Palavra-passe inicial</label><input class="input" id="s-pw" type="password" autocomplete="new-password"><p class="hint">8+ caracteres, maiúscula, número e símbolo.</p></div>
            <div id="s-err"></div>
            <button class="btn btn-primary" type="submit">${icon("plus")} Criar acesso</button>
          </div>
        </form>
      </div>`;
    $("#new", root).addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = (id) => $(`#${id}`, root).value.trim();
      const btn = e.submitter;
      busy(btn, true);
      try {
        await api("/admin/staff", { method: "POST", body: { full_name: v("s-name"), email: v("s-email"), phone: v("s-phone").replace(/\s/g, ""), role: v("s-role"), password: $("#s-pw", root).value } });
        toast("Acesso criado");
        draw();
      } catch (ex) {
        busy(btn, false);
        $("#s-err", root).innerHTML = `<div class="banner banner-bad">${icon("alert")}<span>${esc(ex.status === 409 ? "Já existe um utilizador com este email ou telemóvel." : ex.message)}</span></div>`;
      }
    });
    void fieldError;
  }
  await draw();
}
