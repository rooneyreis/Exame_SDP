// Cliente das APIs existentes (mesma origem, através do nginx).
// Sessão em sessionStorage (desaparece ao fechar o separador). O access token (JWT RS256,
// 15 min) é renovado automaticamente com o refresh token antes de expirar.

const KEY = "gs.session";

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function decodeJwt(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), "=")))));
  } catch {
    return null;
  }
}

export const session = {
  get() {
    try { return JSON.parse(sessionStorage.getItem(KEY)) || null; } catch { return null; }
  },
  set(tokens, profile = {}) {
    const claims = decodeJwt(tokens.access_token);
    const value = { access: tokens.access_token, refresh: tokens.refresh_token, claims, profile: { ...(this.get()?.profile || {}), ...profile } };
    sessionStorage.setItem(KEY, JSON.stringify(value));
    return value;
  },
  clear() { sessionStorage.removeItem(KEY); },
  get claims() { return this.get()?.claims || null; },
};

function detailOf(data, status) {
  if (!data) return `Erro ${status}`;
  const d = data.detail ?? data;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (e.msg || "").replace(/^Value error, /, "")).filter(Boolean).join(" · ") || "Dados inválidos";
  if (d && typeof d === "object") return d.detail || d.status || JSON.stringify(d);
  return `Erro ${status}`;
}

let refreshing = null;

export async function refreshTokens() {
  const s = session.get();
  if (!s?.refresh) throw new ApiError(401, "Sessão expirada");
  if (!refreshing) {
    refreshing = fetch("/auth/refresh", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: s.refresh }),
    }).then(async (r) => {
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new ApiError(r.status, detailOf(data, r.status), data);
      return session.set(data);
    }).finally(() => { refreshing = null; });
  }
  return refreshing;
}

/**
 * api(path, { method, body, headers, auth = true, raw = false })
 * raw: true devolve { ok, status, data, headers } sem lançar exceção (útil nas transferências,
 *      onde 422/202/503 trazem informação de estado no corpo).
 */
export async function api(path, { method = "GET", body, headers = {}, auth = true, raw = false, retried = false } = {}) {
  const s = session.get();
  if (auth && s?.claims?.exp && s.claims.exp * 1000 - Date.now() < 30_000) {
    try { await refreshTokens(); } catch { /* tenta com o token atual; o 401 trata do resto */ }
  }
  const token = session.get()?.access;
  const res = await fetch(path, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).catch((e) => {
    throw new ApiError(0, "Sem ligação ao servidor. Verifique a sua ligação.", { cause: String(e) });
  });

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }

  if (res.status === 401 && auth && !retried && session.get()?.refresh) {
    try {
      await refreshTokens();
      return api(path, { method, body, headers, auth, raw, retried: true });
    } catch {
      session.clear();
      window.dispatchEvent(new CustomEvent("gs:logout", { detail: "expired" }));
    }
  }
  if (raw) return { ok: res.ok, status: res.status, data, headers: res.headers };
  if (!res.ok) throw new ApiError(res.status, detailOf(data, res.status), data);
  return data;
}

export async function login(email, password) {
  const res = await fetch("/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).catch(() => { throw new ApiError(0, "Sem ligação ao servidor."); });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailOf(data, res.status), data);
  return session.set(data, { email });
}

export async function logout() {
  const s = session.get();
  if (s?.refresh) {
    await api("/auth/logout", { method: "POST", body: { refresh_token: s.refresh } }).catch(() => {});
  }
  session.clear();
}

export function newIdempotencyKey() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}
