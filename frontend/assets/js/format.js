// Formatação (pt-PT) e mapeamento dos estados técnicos para linguagem bancária.

const LOCALE = "pt-PT";

export function money(value, currency = "EUR", { sign = false, compact = false } = {}) {
  const n = Number(value ?? 0);
  const fmt = new Intl.NumberFormat(LOCALE, {
    style: "currency", currency, currencyDisplay: "symbol",
    minimumFractionDigits: compact ? 0 : 2, maximumFractionDigits: compact ? 1 : 2,
    notation: compact ? "compact" : "standard",
  });
  const out = fmt.format(Math.abs(n));
  if (!sign) return n < 0 ? `−${out}` : out;
  return n > 0 ? `+${out}` : n < 0 ? `−${out}` : out;
}

export function number(value, digits = 2) {
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value));
}

export function date(value, opts = { day: "2-digit", month: "short", year: "numeric" }) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(LOCALE, opts).format(new Date(value));
}

export function dateTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function time(value) {
  return new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

export function relativeDay(value) {
  const d = new Date(value);
  const today = new Date();
  const diff = Math.round((new Date(today.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (diff === 0) return `Hoje, ${new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" }).format(d)}`;
  if (diff === 1) return `Ontem, ${new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" }).format(d)}`;
  return dateTime(value);
}

/** GS-EU-00000001 -> GS-EU 0000 0001 (legível; o valor real nunca muda) */
export function iban(value) {
  if (!value) return "—";
  return value.replace(/^(GS-[A-Z]{2})-(\d{4})(\d{4})$/, "$1 $2 $3");
}

export function ibanShort(value) {
  return value ? `•••• ${value.slice(-4)}` : "";
}

/** Regiões servidas (espelha GSS_REGIONS do backend): tudo o resto deriva desta tabela. */
export const REGIONS = {
  EU: { name: "Europa", flag: "🇪🇺", currency: "EUR", city: "Lisboa", node: "pg-europa" },
  AM: { name: "América", flag: "🌎", currency: "USD", city: "Nova Iorque", node: "pg-america" },
  AF: { name: "África", flag: "🌍", currency: "MZN", city: "Maputo", node: "pg-africa" },
};
export const REGION_CODES = Object.keys(REGIONS);
const CODES = REGION_CODES.join("|");
/** IBAN completo e válido: GS-EU-00000001 */
export const IBAN_RE = new RegExp(`^GS-(${CODES})-\\d{8}$`);
/** IBAN escrito à pressa (sem hífenes): normaliza com .replace(IBAN_LOOSE_RE, "GS-$1-$2") */
export const IBAN_LOOSE_RE = new RegExp(`^GS-?(${CODES})-?(\\d{8})$`);
/** IBAN ainda incompleto (pesquisa enquanto se escreve) */
export const IBAN_PARTIAL_RE = new RegExp(`^GS-?(${CODES})-?(\\d{1,8})$`);
/** Eventos do 2PC com sufixo de região: PREPARADO_EU, COMMIT_AF… */
export const REGION_SUFFIX_RE = new RegExp(`_(${CODES})$`);
/** "GS-EU-########, GS-AM-######## ou GS-AF-########" */
export const IBAN_FORMATS = REGION_CODES.map((r) => `GS-${r}-########`).join(", ").replace(/, ([^,]*)$/, " ou $1");

export function regionName(code) {
  return REGIONS[code]?.name || code || "—";
}

export function regionOf(ibanValue) {
  const m = new RegExp(`^GS-(${CODES})-`).exec(ibanValue || "");
  return m ? m[1] : null;
}

export const CURRENCY_NAMES = { EUR: "Euro", USD: "Dólar americano", MZN: "Metical" };

/** Estados do coordenador 2PC -> estados que um cliente bancário entende */
export function transferStatus(state) {
  if (state === "CONFIRMADA") return { key: "done", label: "Processada", icon: "check" };
  if (state === "ABORTADA") return { key: "failed", label: "Falhada", icon: "x" };
  return { key: "pending", label: "Pendente", icon: "clock" };
}

export function settlementLabel(status) {
  return {
    "N/A": "Não aplicável (nacional)",
    PENDENTE: "Em liquidação no banco correspondente",
    ACEITE: "Liquidada pelo banco correspondente",
    REJEITADA: "Rejeitada pelo banco correspondente",
  }[status] || status || "—";
}

export function kindLabel(kind) {
  return kind === "DISTRIBUIDA" ? "Internacional" : "Nacional";
}

export function originLabel(origin, type) {
  if (origin === "DEPOSITO") return "Depósito";
  if (origin === "LEVANTAMENTO") return "Levantamento";
  return type === "CREDITO" ? "Transferência recebida" : "Transferência enviada";
}

export function initials(name) {
  return (name || "?").split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
}

export function roleLabel(role) {
  return { cliente: "Cliente particular", operador: "Operador", auditor: "Auditor", admin: "Administrador", service: "Serviço" }[role] || role;
}
