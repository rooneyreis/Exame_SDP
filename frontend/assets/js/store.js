// Dados guardados neste dispositivo (localStorage), por utilizador.
// O backend não tem (de propósito, nesta fase) uma lista de beneficiários nem um endpoint
// "as minhas transferências": os beneficiários e as referências das transferências enviadas
// a partir deste browser ficam aqui. Nada de sensível: só nomes, IBANs e ids de transação.
import { session } from "./api.js";

function key(name) {
  return `gs.${session.claims?.sub || "anon"}.${name}`;
}

function read(name, fallback) {
  try { return JSON.parse(localStorage.getItem(key(name))) ?? fallback; } catch { return fallback; }
}

function write(name, value) {
  try { localStorage.setItem(key(name), JSON.stringify(value)); } catch { /* modo privado: ignora */ }
}

export const beneficiaries = {
  all() { return read("beneficiaries", []).sort((a, b) => (b.favorite - a.favorite) || a.name.localeCompare(b.name)); },
  get(id) { return this.all().find((b) => b.id === id); },
  byIban(iban) { return this.all().find((b) => b.iban === iban); },
  save(b) {
    const list = read("beneficiaries", []).filter((x) => x.id !== b.id && x.iban !== b.iban);
    list.push({ favorite: false, createdAt: new Date().toISOString(), ...b, id: b.id || crypto.randomUUID?.() || String(Date.now()) });
    write("beneficiaries", list);
  },
  remove(id) { write("beneficiaries", read("beneficiaries", []).filter((b) => b.id !== id)); },
  toggleFavorite(id) {
    write("beneficiaries", read("beneficiaries", []).map((b) => (b.id === id ? { ...b, favorite: !b.favorite } : b)));
  },
  touch(iban) {
    write("beneficiaries", read("beneficiaries", []).map((b) => (b.iban === iban ? { ...b, lastUsed: new Date().toISOString() } : b)));
  },
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
