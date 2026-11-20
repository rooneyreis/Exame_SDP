// Estado do cliente no browser: beneficiários (fonte: servidor, com cópia em memória por
// utilizador) e referências das transferências enviadas deste dispositivo (o backend não tem
// um endpoint "as minhas transferências falhadas"). Preferências de aparência.
import { api, session } from "./api.js";

function key(name) {
  return `gs.${session.claims?.sub || "anon"}.${name}`;
}

function read(name, fallback) {
  try { return JSON.parse(localStorage.getItem(key(name))) ?? fallback; } catch { return fallback; }
}

function write(name, value) {
  try { localStorage.setItem(key(name), JSON.stringify(value)); } catch { /* modo privado: ignora */ }
}

/** Beneficiários do cliente, guardados no servidor (GET/POST/PATCH/DELETE /beneficiaries).
 *  Mantém uma cópia em memória para leituras síncronas; load() tem de ser chamado antes. */
let benCache = null, benOwner = null;
export const beneficiaries = {
  async load({ fresh = false } = {}) {
    const owner = session.claims?.sub;
    if (benCache && !fresh && benOwner === owner) return benCache;
    benOwner = owner;
    benCache = await api("/beneficiaries");
    // Migração única: beneficiários que versões anteriores guardavam só neste browser.
    const legacy = read("beneficiaries", []);
    if (legacy.length) {
      for (const b of legacy) {
        if (!benCache.some((x) => x.iban === b.iban)) {
          await api("/beneficiaries", { method: "POST", body: { name: b.name, iban: b.iban, nickname: b.nickname || null, favorite: !!b.favorite } }).catch(() => {});
        }
      }
      try { localStorage.removeItem(key("beneficiaries")); } catch { /* ignore */ }
      benCache = await api("/beneficiaries");
    }
    return benCache;
  },
  all() { return [...(benOwner === session.claims?.sub ? benCache || [] : [])].sort((a, b) => (b.favorite - a.favorite) || a.name.localeCompare(b.name)); },
  get(id) { return this.all().find((b) => b.id === id); },
  byIban(iban) { return this.all().find((b) => b.iban === iban); },
  async save(b) {
    if (b.id) await api(`/beneficiaries/${b.id}`, { method: "PATCH", body: { name: b.name, nickname: b.nickname || null, favorite: !!b.favorite } });
    else await api("/beneficiaries", { method: "POST", body: { name: b.name, iban: b.iban, nickname: b.nickname || null, favorite: !!b.favorite } });
    return this.load({ fresh: true });
  },
  async remove(id) { await api(`/beneficiaries/${id}`, { method: "DELETE" }); return this.load({ fresh: true }); },
  touch() { /* o servidor regista created/updated; nada a fazer no cliente */ },
};

/** Transferências submetidas neste dispositivo (inclui as falhadas, que não geram movimentos). */
export const sentTransfers = {
  all() { return read("sent", []); },
  add(entry) {
    const list = read("sent", []).filter((t) => t.tx_id !== entry.tx_id);
    list.unshift({ at: new Date().toISOString(), ...entry });
    write("sent", list.slice(0, 200));
  },
  get(txId) { return read("sent", []).find((t) => t.tx_id === txId); },
};

export const prefs = {
  get theme() { try { return localStorage.getItem("gs.theme") || "auto"; } catch { return "auto"; } },
  set theme(v) { try { localStorage.setItem("gs.theme", v); } catch { /* ignore */ } applyTheme(); },
  get hideBalances() { try { return localStorage.getItem("gs.hide") === "1"; } catch { return false; } },
  set hideBalances(v) { try { localStorage.setItem("gs.hide", v ? "1" : "0"); } catch { /* ignore */ } },
};

export function applyTheme() {
  const t = prefs.theme;
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}
