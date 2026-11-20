// Gráfico de área de uma só série (evolução do saldo). SVG desenhado à mão:
// linha de 2px, área a ~10%, grelha discreta, ponto final com anel, mira + tooltip ao passar,
// e uma tabela equivalente para leitores de ecrã. Sem legenda: o título do cartão diz o que é.
import { date, money } from "./format.js";
import { esc } from "./ui.js";

function niceTicks(min, max, count = 4) {
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 100) / 100);
  return ticks;
}

function compact(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1).replace(".", ",")}M`;
  if (a >= 1e4) return `${Math.round(v / 1e3)}K`;
  return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0 }).format(v);
}

export function areaChart(host, points, currency, { height = host.clientWidth > 640 ? 300 : 220 } = {}) {
  if (points.length < 2) {
    host.innerHTML = `<div class="empty" style="padding:40px 16px"><p>Ainda não há movimentos suficientes para mostrar a evolução.</p></div>`;
    return;
  }
  // Desenha na largura real do contentor (texto nunca deformado) e redesenha ao redimensionar.
  const W = Math.max(Math.round(host.clientWidth) - 24, 280), H = height, padL = 52, padR = 16, padT = 14, padB = 28;
  if (!host._gsResize) {
    let timer;
    host._gsResize = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => { if (host.isConnected && Math.abs(host.clientWidth - 24 - W) > 8) areaChart(host, points, currency, { height }); }, 120);
    });
    host._gsResize.observe(host);
  }
  const t0 = points[0].t, t1 = points[points.length - 1].t || t0 + 1;
  const vals = points.map((p) => p.v);
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals));
  const yMin = ticks[0], yMax = ticks[ticks.length - 1];
  const x = (t) => padL + ((t - t0) / Math.max(t1 - t0, 1)) * (W - padL - padR);
  const y = (v) => padT + (1 - (v - yMin) / Math.max(yMax - yMin, 1e-9)) * (H - padT - padB);

  // degraus: o saldo mantém-se até ao movimento seguinte
  let d = `M${x(points[0].t)},${y(points[0].v)}`;
  for (let i = 1; i < points.length; i++) d += ` H${x(points[i].t)} V${y(points[i].v)}`;
  const area = `${d} V${y(yMin)} H${x(points[0].t)} Z`;
  const last = points[points.length - 1];

  let xTicks = W < 420 ? [t0, t1] : [t0, t0 + (t1 - t0) / 2, t1];
  const sameDay = t1 - t0 < 36 * 3600 * 1000;    // tudo no mesmo dia: eixo em horas
  const tickLabel = (t) => sameDay
    ? new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(t)
    : date(t, { day: "2-digit", month: "short" });
  xTicks = xTicks.filter((t, i) => i === 0 || i === xTicks.length - 1 || (tickLabel(t) !== tickLabel(xTicks[0]) && tickLabel(t) !== tickLabel(xTicks[xTicks.length - 1])));
  host.innerHTML = `
    <div class="chart">
      <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Evolução do saldo">
        <g class="axis">
          ${ticks.map((v) => `<line class="gridline" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>
            <text x="${padL - 10}" y="${y(v) + 4}" text-anchor="end">${compact(v)}</text>`).join("")}
          ${xTicks.map((t, i) => `<text x="${x(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}">${esc(tickLabel(t))}</text>`).join("")}
        </g>
        <path class="area" d="${area}"/>
        <path class="line" d="${d}"/>
        <line class="cross" x1="0" x2="0" y1="${padT}" y2="${H - padB}"/>
        <circle class="hover-dot" r="5" cx="0" cy="0"/>
        <circle class="end-dot" r="4.5" cx="${x(last.t)}" cy="${y(last.v)}"/>
        <rect class="hit" x="${padL}" y="0" width="${W - padL - padR}" height="${H}" fill="transparent"/>
      </svg>
      <div class="chart-tip"></div>
      <table class="sr-only"><caption>Saldo ao longo do tempo</caption><tbody>
        ${points.map((p) => `<tr><th>${esc(date(p.t))}</th><td>${esc(money(p.v, currency))}</td></tr>`).join("")}
      </tbody></table>
    </div>`;

  const wrap = host.querySelector(".chart");
  const svg = wrap.querySelector("svg");
  const tip = wrap.querySelector(".chart-tip");
  const cross = svg.querySelector(".cross");
  const dot = svg.querySelector(".hover-dot");

  function show(clientX) {
    const r = svg.getBoundingClientRect();
    const vx = ((clientX - r.left) / r.width) * W;
    const t = t0 + ((vx - padL) / (W - padL - padR)) * (t1 - t0);
    let p = points[0];
    for (const q of points) if (q.t <= t) p = q;       // valor em vigor nesse instante
    const px = Math.min(Math.max(vx, padL), W - padR);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px);
    dot.setAttribute("cx", px); dot.setAttribute("cy", y(p.v));
    tip.innerHTML = `<b class="num">${esc(money(p.v, currency))}</b><span class="muted">${esc(new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(p.t))}</span>`;
    tip.style.left = `${(px / W) * r.width + 12}px`;
    tip.style.top = `${(y(p.v) / H) * r.height + 8}px`;
    wrap.classList.add("hovering");
  }
  svg.addEventListener("pointermove", (e) => show(e.clientX));
  svg.addEventListener("pointerdown", (e) => show(e.clientX));
  svg.addEventListener("pointerleave", () => wrap.classList.remove("hovering"));
}

/**
 * Colunas de uma só série (ex.: transferências processadas por dia). Barras ≤ 24 px com
 * topo arredondado, base reta na linha de base, valor no topo da última, tooltip por barra.
 * rows: [{ label, value, detail }]
 */
export function barChart(host, rows, { height = 240, format = (v) => String(v) } = {}) {
  if (!rows.length) { host.innerHTML = `<div class="empty" style="padding:40px 16px"><p>Sem dados no período.</p></div>`; return; }
  const W = Math.max(Math.round(host.clientWidth) - 24, 280), H = height, padL = 40, padR = 12, padT = 18, padB = 28;
  const max = Math.max(...rows.map((r) => r.value), 1);
  const ticks = niceTicks(0, max, 4);
  const top = ticks[ticks.length - 1];
  const band = (W - padL - padR) / rows.length;
  const bw = Math.min(24, band * 0.6);
  const y = (v) => padT + (1 - v / top) * (H - padT - padB);
  const step = Math.ceil(rows.length / Math.max(Math.floor((W - padL) / 56), 1));
  host.innerHTML = `
    <div class="chart">
      <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Gráfico de colunas">
        <g class="axis">${ticks.map((v) => `<line class="gridline" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>
          <text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end">${compact(v)}</text>`).join("")}
          ${rows.map((r, i) => (i % step === 0 || i === rows.length - 1) ? `<text x="${padL + band * i + band / 2}" y="${H - 8}" text-anchor="middle">${esc(r.label)}</text>` : "").join("")}
        </g>
        ${rows.map((r, i) => {
          const x = padL + band * i + (band - bw) / 2, h = Math.max(y(0) - y(r.value), r.value ? 2 : 0), rad = Math.min(4, h);
          return `<path class="bar" data-i="${i}" d="M${x},${y(0)} V${y(0) - h + rad} Q${x},${y(0) - h} ${x + rad},${y(0) - h} H${x + bw - rad} Q${x + bw},${y(0) - h} ${x + bw},${y(0) - h + rad} V${y(0)} Z"/>
            <rect class="bar-hit" data-i="${i}" x="${padL + band * i}" y="${padT}" width="${band}" height="${H - padT - padB}" fill="transparent"/>`;
        }).join("")}
        <text class="bar-value" x="${padL + band * (rows.length - 1) + band / 2}" y="${y(rows[rows.length - 1].value) - 6}" text-anchor="middle">${esc(format(rows[rows.length - 1].value))}</text>
      </svg>
      <div class="chart-tip"></div>
      <table class="sr-only"><tbody>${rows.map((r) => `<tr><th>${esc(r.label)}</th><td>${esc(format(r.value))}</td></tr>`).join("")}</tbody></table>
    </div>`;
  const wrap = host.querySelector(".chart"), tip = wrap.querySelector(".chart-tip"), svg = wrap.querySelector("svg");
  svg.querySelectorAll(".bar-hit").forEach((hit) => {
    hit.addEventListener("pointerenter", () => {
      const r = rows[hit.dataset.i];
      svg.querySelectorAll(".bar").forEach((b) => b.classList.toggle("dim", b.dataset.i !== hit.dataset.i));
      const box = svg.getBoundingClientRect(), hb = hit.getBoundingClientRect();
      tip.innerHTML = `<b class="num">${esc(format(r.value))}</b><span class="muted">${esc(r.label)}${r.detail ? ` · ${esc(r.detail)}` : ""}</span>`;
      tip.style.left = `${hb.left - box.left + hb.width / 2}px`;
      tip.style.top = `${(y(r.value) / H) * box.height}px`;
      wrap.classList.add("hovering");
    });
  });
  svg.addEventListener("pointerleave", () => { wrap.classList.remove("hovering"); svg.querySelectorAll(".bar").forEach((b) => b.classList.remove("dim")); });
}
