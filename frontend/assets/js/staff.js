// Peças partilhadas pelos painéis de Administrador, Operador e Auditor.
import { api } from "./api.js";
import { dateTime, iban, kindLabel, money, transferStatus } from "./format.js";
import { icon } from "./icons.js";
import { esc, statusChip } from "./ui.js";

let directory = null;     // id -> utilizador (nomes em vez de UUIDs)

export async function users({ fresh = false } = {}) {
  if (!directory || fresh) {
    const list = await api("/admin/users");
    directory = new Map(list.map((u) => [u.id, u]));
  }
  return directory;
}

export function who(dir, id) {
  if (!id) return "—";
  const u = dir?.get(id);
  return u ? u.full_name : `${id.slice(0, 8)}…`;
}

export const ROLE_LABEL = { cliente: "Cliente", operador: "Operador", auditor: "Auditor", admin: "Administrador" };
export function roleBadge(role) {
  return `<span class="role-badge role-${esc(role)}">${esc(ROLE_LABEL[role] || role)}</span>`;
}

export const REQUEST_STATUS = {
  PENDENTE_APROVACAO: { key: "pending", label: "Pendente de aprovação", icon: "clock" },
  EM_EXECUCAO: { key: "pending", label: "Em processamento", icon: "clock" },
  EXECUTADA: { key: "done", label: "Concluída", icon: "check" },
  REJEITADA: { key: "failed", label: "Rejeitada", icon: "x" },
  FALHADA: { key: "failed", label: "Falhada", icon: "alert" },
};
export function requestChip(status) {
  return statusChip(REQUEST_STATUS[status] || { key: "pending", label: status, icon: "clock" });
}

export function userStatusChip(status) {
  const map = { ATIVA: ["done", "Ativa"], BLOQUEADA: ["failed", "Bloqueada"], DESATIVADA: ["failed", "Desativada"],
    PENDENTE_VERIFICACAO: ["pending", "Pendente"] };
  const [k, l] = map[status] || ["pending", status];
  return `<span class="chip status-${k}">${esc(l)}</span>`;
}

/** Tabela de transferências usada pelos três perfis. */
export function transfersTable(items, dir, { showActors = true } = {}) {
  if (!items.length) return `<div class="empty"><div class="tx-icon">${icon("search")}</div><h3>Sem transferências</h3><p>Ajuste os filtros.</p></div>`;
  return `<div class="table-wrap"><table class="table">
    <thead><tr><th>Data</th><th>Origem → Destino</th><th class="hide-sm">Tipo</th>${showActors ? `<th class="hide-sm">Iniciada por</th><th class="hide-sm">Aprovada por</th>` : ""}<th>Estado</th><th class="r">Montante</th></tr></thead>
    <tbody>${items.map((t) => `
      <tr class="clickable" data-tx="${esc(t.tx_id)}" tabindex="0">
        <td class="num" style="white-space:nowrap">${esc(dateTime(t.created_at))}</td>
        <td><span class="mono">${esc(iban(t.from_iban))}</span><br><span class="mono muted">→ ${esc(iban(t.to_iban))}</span></td>
        <td class="hide-sm"><span class="chip ${t.kind === "DISTRIBUIDA" ? "chip-accent" : ""}">${esc(kindLabel(t.kind))}</span></td>
        ${showActors ? `<td class="hide-sm">${esc(who(dir, t.initiated_by))}<div class="hint">${esc(ROLE_LABEL[t.initiated_role] || t.initiated_role)}</div></td>
        <td class="hide-sm">${t.approved_by ? esc(who(dir, t.approved_by)) : `<span class="muted">—</span>`}</td>` : ""}
        <td>${statusChip(transferStatus(t.state))}${t.failure_reason ? `<div class="hint" style="max-width:220px">${esc(t.failure_reason)}</div>` : ""}</td>
        <td class="r"><span class="amount num">${esc(money(t.amount, t.from_currency))}</span>${t.from_currency !== t.to_currency ? `<div class="hint num">→ ${esc(money(t.converted_amount, t.to_currency))}</div>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>`;
}

export function bindRowLinks(root, navigate) {
  root.querySelectorAll("[data-tx]").forEach((tr) => {
    const go = () => navigate(`/tx/${encodeURIComponent(tr.dataset.tx)}`);
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });
}

export function downloadCsv(filename, header, rows) {
  const csv = [header, ...rows].map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(";")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function exportButtons() {
  return `<button class="btn btn-secondary" data-export="csv">${icon("download")} CSV</button>
          <button class="btn btn-secondary" data-export="pdf">${icon("print")} PDF</button>`;
}

export function kpi(label, value, sub = "", iconName = "") {
  return `<div class="card card-pad stat"><div class="label">${iconName ? icon(iconName) : ""}${esc(label)}</div>
    <div class="value num">${value}</div>${sub ? `<div class="delta">${sub}</div>` : ""}</div>`;
}

/** Série diária (últimos N dias) de transferências processadas a partir de /admin/overview. */
export function dailySeries(daily, days = 14) {
  const byDay = new Map();
  for (const d of daily) {
    const k = d.day.slice(0, 10);
    const cur = byDay.get(k) || { confirmed: 0, failed: 0 };
    cur.confirmed += Number(d.confirmed); cur.failed += Number(d.failed);
    byDay.set(k, cur);
  }
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const dt = new Date(Date.now() - i * 86400000);
    const k = dt.toISOString().slice(0, 10);
    const v = byDay.get(k) || { confirmed: 0, failed: 0 };
    out.push({ label: new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit" }).format(dt),
      value: v.confirmed, detail: v.failed ? `${v.failed} falhadas` : "" });
  }
  return out;
}
