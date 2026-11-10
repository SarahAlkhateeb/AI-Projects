import React from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { AbsoluteFill } from "remotion";
import { useReveal } from "../motion";
import type { Theme } from "../types";

type P = { theme: Theme; continued?: boolean } & Record<string, any>;

// ---------- defensive prop handling (the storyboard LLM sometimes sends JSON strings, or junk)
const isObj = (v: any) => !!v && typeof v === "object" && !Array.isArray(v);
const tryJson = (v: any) => {
  if (typeof v !== "string") return v; const s = v.trim();
  if (!(s.startsWith("[") || s.startsWith("{"))) return v;
  try { return JSON.parse(s); } catch { return v; }
};
const num = (v: any, fb: number) => {
  const n = typeof v === "number" ? v : typeof v === "string" ? parseFloat(v.replace(/,/g, "")) : NaN;
  return Number.isFinite(n) ? n : fb;
};
const has = (v: any) => v !== undefined && v !== null && v !== "";
const c01 = (v: number) => Math.max(0, Math.min(1, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const ARR_KEYS = new Set(["items", "lines", "values", "labels", "nodes", "edges", "x_range", "y_range", "bars_at", "bars", "points", "series", "x_labels", "highlight_range"]);
const NUM_ARR = new Set(["x_range", "y_range", "bars_at", "values", "highlight_range"]);
const PAIR = new Set(["x_range", "y_range", "highlight_range"]);
const OBJ_KEYS = new Set(["left", "right", "chart", "prevProps"]);
const CAPS: Record<string, number> = { items: 8, lines: 6, values: 24, labels: 24, nodes: 24, edges: 60, bars_at: 24, bars: 24, series: 6, x_labels: 12 };
/** Parse JSON-string props, drop wrongly-typed structured props, cap list sizes. Never throws. */
export function coerceProps(raw: any): Record<string, any> {
  const p = tryJson(raw); if (!isObj(p)) return {};
  const out: Record<string, any> = {};
  for (const [k, v0] of Object.entries(p)) {
    let v: any = v0;
    if (ARR_KEYS.has(k) || OBJ_KEYS.has(k)) v = tryJson(v);
    if (ARR_KEYS.has(k)) {
      if (!Array.isArray(v)) continue;
      if (NUM_ARR.has(k)) v = v.map((n: any) => num(n, NaN)).filter((n: number) => Number.isFinite(n));
      if (k === "nodes" || k === "edges") v = v.filter(isObj);
      if (PAIR.has(k) && v.length !== 2) continue;
      if (CAPS[k]) v = v.slice(0, CAPS[k]);
    } else if (OBJ_KEYS.has(k)) {
      if (!isObj(v)) continue;
      if (k === "prevProps") v = coerceProps(v);
    } else if (v !== null && typeof v === "object") {
      v = JSON.stringify(v); // a scalar prop that arrived as object/array: show as text instead of crashing React
    }
    out[k] = v;
  }
  return out;
}
const safe = (C: React.FC<any>): React.FC<any> => ({ theme, continued, prevProps, ...rest }: any) =>
  <C {...coerceProps(rest)} prev={has(prevProps) ? coerceProps(prevProps) : undefined} continued={!!continued} theme={theme} />;

const colorize = (tex: string, h: string | undefined, color: string) => {
  if (!h) return tex; const i = tex.lastIndexOf(h);
  return i < 0 ? tex : tex.slice(0, i) + `\\textcolor{${color}}{${h}}` + tex.slice(i + h.length);
};
const Tex = ({ tex, size = 80, color }: { tex: string; size?: number; color: string }) => (
  <span style={{ fontSize: size, color }} dangerouslySetInnerHTML={{ __html: katex.renderToString(tex, { throwOnError: false, displayMode: true }) }} />
);
const Center: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: 140, textAlign: "center" }}>{children}</AbsoluteFill>
);
const mark = (text: string, sub: string | undefined, color: string) => {
  if (!sub || !text.includes(sub)) return text;
  const [a, b] = text.split(sub, 2);
  return <>{a}<span style={{ color }}>{sub}</span>{b}</>;
};

// ---------- text
const TitleCard = ({ theme, title, subtitle }: P) => { const p = useReveal(theme, 1);
  return <Center><div style={{ opacity: p, transform: `translateY(${(1 - p) * 30}px)` }}>
    <div style={{ fontSize: 96, fontWeight: 700 }}>{title}</div>
    {subtitle && <div style={{ fontSize: 44, color: theme.palette.accent, marginTop: 24 }}>{subtitle}</div>}</div></Center>; };

const Callout = ({ theme, text, emphasis }: P) => { const p = useReveal(theme, 0.7);
  return <Center><div style={{ fontSize: 68, lineHeight: 1.3, opacity: p, maxWidth: 1500, transform: `translateY(${(1 - p) * 20}px)` }}>{mark(text, emphasis, theme.palette.accent)}</div></Center>; };

const Bullet = ({ theme, text, k }: { theme: Theme; text: string; k: number }) => { const p = useReveal(theme, 0.5, k * 0.8);
  return <div style={{ fontSize: 60, margin: "22px 0", opacity: p, transform: `translateX(${(1 - p) * 40}px)` }}>
    <span style={{ color: theme.palette.accent, marginRight: 24 }}>•</span>{text}</div>; };
const BulletBuild = ({ theme, items = [] }: P) => (
  <Center><div style={{ textAlign: "left" }}>{items.map((it: string, k: number) => <Bullet key={k} theme={theme} text={it} k={k} />)}</div></Center>);

const Misconception = ({ theme, claim, correction }: P) => { const p = useReveal(theme, 1, 1.6);
  return <Center><div style={{ fontSize: 62, maxWidth: 1500 }}>
    <div style={{ textDecoration: p > 0.5 ? "line-through" : "none", opacity: 1 - 0.5 * p }}>{claim}</div>
    <div style={{ marginTop: 50, color: theme.palette.accent, opacity: p, transform: `translateY(${(1 - p) * 30}px)` }}>{correction}</div></div></Center>; };

const Line = ({ theme, l, k }: { theme: Theme; l: string; k: number }) => { const p = useReveal(theme, 1.2, k * 1.4); const n = Math.floor(p * l.length);
  return <div style={{ fontSize: 64, margin: "18px 0", fontFamily: "'Caveat', 'Bradley Hand', cursive", whiteSpace: "pre-wrap" }}>{l.slice(0, n)}<span style={{ opacity: p < 1 ? 1 : 0 }}>|</span></div>; };
const WhiteboardWrite = ({ theme, lines = [] }: P) => (
  <AbsoluteFill style={{ padding: 140, justifyContent: "center" }}>{lines.map((l: string, k: number) => <Line key={k} theme={theme} l={l} k={k} />)}</AbsoluteFill>);

// ---------- math
const Equation = ({ theme, tex, highlight }: P) => { const p = useReveal(theme, 0.8);
  return <Center><div style={{ opacity: p, transform: `scale(${0.92 + 0.08 * p})` }}><Tex tex={colorize(tex, highlight, theme.palette.accent)} color={theme.palette.fg} /></div></Center>; };

const EquationMorph = ({ theme, from_tex, to_tex, highlight }: P) => { const p = useReveal(theme, 1.2, 1.0);
  return <Center>
    <div style={{ position: "absolute", opacity: 1 - p, transform: `scale(${1 - 0.15 * p}) translateY(${-40 * p}px)` }}><Tex tex={from_tex} color={theme.palette.fg} /></div>
    <div style={{ position: "absolute", opacity: p, transform: `scale(${0.85 + 0.15 * p}) translateY(${40 * (1 - p)}px)` }}><Tex tex={colorize(to_tex, highlight, theme.palette.accent)} color={theme.palette.fg} /></div>
  </Center>; };

// ---------- scenes (persist across shots; props animate)
const Plot = ({ theme, fn, x_range = [-3, 3], y_range = [-1, 8], label, point_at, tangent_at, bars_at = [], draw, continued }: P) => {
  const pDraw = useReveal(theme, 2); const pIn = useReveal(theme, 0.6);
  const W = 1400, H = 760, N = 240;
  const f = (x: number) => { try { const v = Function("x", `return ${fn}`)(x); return Number.isFinite(v) ? v : 0; } catch { return 0; } };
  const sx = (x: number) => ((x - x_range[0]) / (x_range[1] - x_range[0])) * W;
  const sy = (y: number) => H - ((y - y_range[0]) / (y_range[1] - y_range[0])) * H;
  const pts = Array.from({ length: N + 1 }, (_, k) => { const x = x_range[0] + (k / N) * (x_range[1] - x_range[0]); return [sx(x), sy(f(x))]; });
  const frac = draw && !continued ? pDraw : 1;
  const shown = pts.slice(0, Math.max(2, Math.floor(frac * pts.length)));
  const muted = theme.palette.muted ?? theme.palette.fg;
  const slope = (x: number) => { const h = 1e-3; return (f(x + h) - f(x - h)) / (2 * h); };
  const xstep = Math.max(1, Math.ceil((x_range[1] - x_range[0]) / 12));
  const xticks: number[] = []; for (let v = Math.ceil(x_range[0] / xstep) * xstep; v <= Math.floor(x_range[1]); v += xstep) xticks.push(v);
  const ystep = Math.max(1, Math.round((y_range[1] - y_range[0]) / 6));
  const yticks: number[] = []; for (let v = Math.ceil(y_range[0] / ystep) * ystep; v <= y_range[1]; v += ystep) yticks.push(v);
  return <Center><svg width={W} height={H} style={{ overflow: "visible" }}>
    {xticks.map((v) => <line key={"gx" + v} x1={sx(v)} y1={0} x2={sx(v)} y2={H} stroke={muted} strokeOpacity={0.08} strokeWidth={1} />)}
    {yticks.map((v) => <line key={"gy" + v} x1={0} y1={sy(v)} x2={W} y2={sy(v)} stroke={muted} strokeOpacity={0.08} strokeWidth={1} />)}
    <line x1={0} y1={sy(0)} x2={W} y2={sy(0)} stroke={muted} strokeOpacity={0.4} strokeWidth={2} />
    <line x1={sx(0)} y1={0} x2={sx(0)} y2={H} stroke={muted} strokeOpacity={0.4} strokeWidth={2} />
    {xticks.map((v) => <g key={"t" + v}><line x1={sx(v)} y1={sy(0) - 7} x2={sx(v)} y2={sy(0) + 7} stroke={muted} strokeOpacity={0.6} strokeWidth={2} />
      <text x={sx(v)} y={sy(0) + 38} textAnchor="middle" fontSize={26} fill={muted} fillOpacity={0.8}>{v}</text></g>)}
    {yticks.filter((v) => v !== 0).map((v) => <text key={"ty" + v} x={sx(0) - 14} y={sy(v) + 9} textAnchor="end" fontSize={26} fill={muted} fillOpacity={0.8}>{v}</text>)}
    {bars_at.map((x: number, k: number) => <g key={k} opacity={pIn}>
      <rect x={sx(x) - 14} y={sy(f(x))} width={28} height={sy(0) - sy(f(x))} fill={theme.palette.accent} opacity={0.55} />
      <text x={sx(x)} y={sy(f(x)) - 16} textAnchor="middle" fontSize={28} fill={theme.palette.accent}>{f(x).toFixed(2)}</text>
      <text x={sx(x)} y={sy(0) + 44} textAnchor="middle" fontSize={30} fill={theme.palette.fg} fillOpacity={0.9}>x={x}</text></g>)}
    <polyline points={shown.map((q) => q.join(",")).join(" ")} fill="none" stroke={theme.palette.accent} strokeWidth={7} strokeLinecap="round" />
    {tangent_at !== undefined && (() => { const m = slope(tangent_at), y0 = f(tangent_at), x1 = tangent_at - 1.1, x2 = tangent_at + 1.1;
      return <g opacity={pIn}><line x1={sx(x1)} y1={sy(y0 + m * (x1 - tangent_at))} x2={sx(x2)} y2={sy(y0 + m * (x2 - tangent_at))} stroke={theme.palette.accent2} strokeWidth={5} />
        <text x={sx(x2) + 16} y={sy(y0 + m * (x2 - tangent_at))} fontSize={34} fill={theme.palette.accent2}>slope {m.toFixed(2)}</text></g>; })()}
    {(point_at ?? tangent_at) !== undefined && (() => { const x = point_at ?? tangent_at; const y = f(x);
      return <g opacity={pIn}><line x1={sx(x)} y1={sy(0)} x2={sx(x)} y2={sy(y)} stroke={theme.palette.fg} strokeOpacity={0.5} strokeDasharray="8 8" strokeWidth={3} />
        <circle cx={sx(x)} cy={sy(y)} r={13} fill={theme.palette.accent2} />
        <text x={sx(x) - 16} y={sy(y) - 22} textAnchor="end" fontSize={34} fill={theme.palette.fg}>height {y.toFixed(2)}</text></g>; })()}
    {label && <text x={W - 20} y={40} textAnchor="end" fontSize={44} fill={theme.palette.fg}>{label}</text>}
  </svg></Center>; };

const NumberLine = ({ theme, values = [], labels = [], highlight_index }: P) => { const p = useReveal(theme, 1);
  const W = 1500, y = 540, n = values.length; const X = (k: number) => 210 + (k / Math.max(1, n - 1)) * W;
  return <AbsoluteFill><svg width={1920} height={1080}>
    <line x1={160} y1={y} x2={1760} y2={y} stroke={theme.palette.fg} strokeOpacity={0.5} strokeWidth={3} />
    {values.map((v: number, k: number) => { const on = k === highlight_index; const q = Math.min(1, Math.max(0, p * n - k));
      return <g key={k} opacity={q}><circle cx={X(k)} cy={y} r={on ? 20 : 12} fill={on ? theme.palette.accent2 : theme.palette.accent} />
        <text x={X(k)} y={y - 40} textAnchor="middle" fontSize={on ? 52 : 40} fill={on ? theme.palette.accent2 : theme.palette.fg}>{labels[k] ?? v}</text></g>; })}
  </svg></AbsoluteFill>; };

const DiagramNodes = ({ theme, nodes = [], edges = [], highlight, continued }: P) => { const p = useReveal(theme, continued ? 0.4 : 1.4);
  const pos: Record<string, [number, number]> = {}; const cx = 960, cy = 540, R = 340;
  nodes.forEach((n: any, k: number) => { const a = (k / nodes.length) * 2 * Math.PI - Math.PI / 2; pos[n.id] = [cx + R * Math.cos(a), cy + R * Math.sin(a)]; });
  const ep = continued ? 1 : p;
  return <AbsoluteFill><svg width={1920} height={1080}>
    {edges.map((e: any, k: number) => { const a = pos[e.from], b = pos[e.to]; if (!a || !b) return null;
      return <line key={k} x1={a[0]} y1={a[1]} x2={a[0] + (b[0] - a[0]) * ep} y2={a[1] + (b[1] - a[1]) * ep} stroke={theme.palette.accent2} strokeWidth={5} />; })}
    {nodes.map((n: any, k: number) => { const [x, y] = pos[n.id]; const q = continued ? 1 : Math.min(1, p * nodes.length - k); const on = n.id === highlight;
      return <g key={n.id} opacity={Math.max(0, q)}><circle cx={x} cy={y} r={on ? 100 + 10 * p : 90} fill={on ? theme.palette.accent2 : theme.palette.accent} />
        <text x={x} y={y + 14} textAnchor="middle" fontSize={38} fill={theme.palette.bg} fontWeight={700}>{n.label}</text></g>; })}
  </svg></AbsoluteFill>; };

// ---------- data charts (bar_chart, line_chart, compare_split, stat_reveal)
// Hard caps so a bad prop cannot freeze the renderer.
const MAX_BARS = 24, MAX_POINTS = 400, MAX_TICKS = 12, MAX_SERIES = 6;

const decOf = (step: number) => { const s = String(Number(step.toPrecision(10))); const i = s.indexOf("."); return i < 0 ? 0 : Math.min(6, s.length - i - 1); };
const commas = (s: string) => { const [a, b] = s.split("."); return a.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (b ? "." + b : ""); };
const fmtVal = (v: number, dec?: number) => !Number.isFinite(v) ? "" : commas(dec === undefined ? String(Number(v.toFixed(2))) : v.toFixed(dec));
const withUnit = (s: string, unit?: string) => !unit ? s : /^[%°x×]/.test(unit) || unit.length <= 1 ? s + unit : s + " " + unit;
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s);

/** "Nice" tick values in [lo, hi]; never more than `cap`. */
function niceTicks(lo: number, hi: number, target = 5, cap = MAX_TICKS) {
  const span = hi - lo; if (!(span > 0) || !Number.isFinite(span)) return { ticks: [lo], step: 1 };
  const raw = span / target; const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw * 0.999) ?? 10 * mag;
  const first = Math.ceil(lo / step - 1e-9); const ticks: number[] = [];
  for (let i = first; ticks.length < cap; i++) { const v = Number((i * step).toPrecision(12)); if (v > hi + step * 1e-9) break; ticks.push(v); }
  return { ticks, step };
}

type Bar = { label: string; value: number };
const readBars = (raw: any): Bar[] => (Array.isArray(raw) ? raw : []).slice(0, MAX_BARS).map((b: any) => {
  if (isObj(b)) return { label: String(b.label ?? b.name ?? ""), value: num(b.value ?? b.y, 0) };
  if (Array.isArray(b)) return { label: String(b[0] ?? ""), value: num(b[1], 0) };
  return { label: "", value: num(b, 0) };
});
/** Resolve the value axis. y_min is honoured literally: that is the "misleading axis" trick. */
function barAxis(bars: Bar[], p: Record<string, any>) {
  const vals = bars.map((b) => b.value);
  const hi = vals.length ? vals.reduce((a, b) => Math.max(a, b)) : 1, lo = vals.length ? vals.reduce((a, b) => Math.min(a, b)) : 0;
  const ymin = has(p.y_min) ? num(p.y_min, 0) : lo < 0 ? lo * 1.15 : 0;
  let ymax = has(p.y_max) ? num(p.y_max, NaN) : NaN;
  if (!Number.isFinite(ymax)) ymax = ymin > 0 ? hi + 0.25 * (hi - ymin) : hi > 0 ? hi * 1.15 : 0;
  if (!(ymax > ymin)) ymax = ymin + (Math.abs(ymin) || 1);
  return { ymin, ymax };
}

type Common = { theme: Theme; p: Record<string, any>; prev?: Record<string, any>; m: number; pIn: number; W: number; H: number; continued: boolean };

const BarSvg = ({ theme, p, prev, m, pIn, W, H, continued }: Common) => {
  const bars = readBars(p.bars); const n = bars.length;
  const ca = barAxis(bars, p);
  const pbars = prev ? readBars(prev.bars) : []; const pa = prev ? barAxis(pbars, prev) : ca;
  const ymin = lerp(pa.ymin, ca.ymin, m), ymax = lerp(pa.ymax, ca.ymax, m);
  const muted = theme.palette.muted ?? theme.palette.fg;
  const title = has(p.title) ? String(p.title) : ""; const unit = has(p.unit) ? String(p.unit) : "";
  const showValues = p.show_values !== false && p.show_values !== "false";
  const hl = has(p.highlight_index) ? num(p.highlight_index, -1) : -1;
  const L = 150, R = 40, T = title ? 110 : 50, B = 110; const x1 = W - R, top = T, bottom = H - B;
  const sy = (v: number) => Math.max(top, Math.min(bottom, bottom - ((v - ymin) / (ymax - ymin)) * (bottom - top)));
  const base = Math.max(ymin, Math.min(ymax, 0));
  const axisOp = continued ? 1 : c01(pIn * 3);
  const { ticks, step } = niceTicks(ymin, ymax, 5);
  const dec = decOf(step);
  const slot = n ? (x1 - L) / n : 1; const barW = Math.min(slot * 0.62, 240);
  const vs = n <= 4 ? 48 : n <= 6 ? 42 : n <= 10 ? 34 : n <= 16 ? 26 : 20;
  const cs = n <= 4 ? 38 : n <= 6 ? 34 : n <= 10 ? 28 : n <= 16 ? 22 : 18;
  const breakOp = lerp(pa.ymin > 0 ? 1 : 0, ca.ymin > 0 ? 1 : 0, m) * axisOp;
  const yb = bottom - 34;
  const zig = (y: number) => { let d = `M ${L - 16} ${y}`; for (let x = L - 16, k = 0; x < x1 + 12 && k < 80; x += 22, k++) d += ` L ${x + 11} ${y - 6} L ${x + 22} ${y}`; return d; };
  return <svg width={W} height={H} style={{ overflow: "visible" }}>
    {title && <text x={W / 2} y={60} textAnchor="middle" fontSize={46} fill={theme.palette.fg} opacity={axisOp}>{title}</text>}
    <g opacity={axisOp}>
      {ticks.map((v, k) => <g key={"g" + k}><line x1={L} y1={sy(v)} x2={x1} y2={sy(v)} stroke={muted} strokeOpacity={0.14} strokeWidth={1} />
        <text x={L - 18} y={sy(v) + 10} textAnchor="end" fontSize={28} fill={muted} fillOpacity={0.9}
          opacity={ca.ymin > 0 && Math.abs(v - ymin) < step * 0.3 ? 0 : 1}>{fmtVal(v, dec)}</text></g>)}
      <line x1={L} y1={top} x2={L} y2={bottom} stroke={muted} strokeOpacity={0.5} strokeWidth={3} />
      <text x={L - 18} y={bottom + 10} textAnchor="end" fontSize={28} fontWeight={700} fill={ca.ymin > 0 ? theme.palette.accent2 : muted}
        opacity={ca.ymin > 0 ? 1 : 0}>{fmtVal(ca.ymin, Math.max(dec, decOf(ca.ymin)))}</text>
      <line x1={L} y1={sy(base)} x2={x1} y2={sy(base)} stroke={muted} strokeOpacity={0.5} strokeWidth={3} />
    </g>
    {bars.map((b, k) => {
      const cx = L + slot * (k + 0.5); const on = k === hl;
      const pv = pbars[k]?.value; const v = continued && prev ? lerp(pv ?? ca.ymin, b.value, m) : b.value;
      const shown = base + (v - base) * (continued ? 1 : pIn);
      const yv = sy(shown), y0 = sy(base);
      const up = shown >= base;
      const lblOp = continued ? 1 : c01((pIn - 0.55) * 2.2);
      return <g key={k}>
        <rect x={cx - barW / 2} y={Math.min(yv, y0)} width={barW} height={Math.abs(y0 - yv)} fill={on ? theme.palette.accent2 : theme.palette.accent} opacity={hl >= 0 && !on ? 0.55 : 0.92} rx={3} />
        {showValues && <text x={cx} y={up ? yv - 16 : yv + vs + 6} textAnchor="middle" fontSize={vs} fontWeight={700} opacity={lblOp}
          fill={on ? theme.palette.accent2 : theme.palette.fg}>{withUnit(fmtVal(v), unit)}</text>}
        <text x={cx} y={bottom + 18 + cs} textAnchor="middle" fontSize={cs} fill={theme.palette.fg} fillOpacity={0.9} opacity={axisOp}>{clip(b.label, Math.max(4, Math.floor(slot / (cs * 0.55))))}</text>
      </g>;
    })}
    {breakOp > 0.01 && <g opacity={breakOp}>
      <rect x={L - 20} y={yb - 9} width={x1 - L + 40} height={18} fill={theme.palette.bg} />
      <path d={zig(yb - 9)} fill="none" stroke={theme.palette.accent2} strokeWidth={3} strokeLinejoin="round" />
      <path d={zig(yb + 9)} fill="none" stroke={theme.palette.accent2} strokeWidth={3} strokeLinejoin="round" />
    </g>}
  </svg>;
};

type Pt = { x: number; y: number }; type Ser = { name: string; pts: Pt[] };
const readPts = (raw: any): Pt[] => {
  const a = Array.isArray(raw) ? raw : []; const n = a.length; const stride = Math.max(1, Math.ceil(n / (MAX_POINTS - 1)));
  const idx: number[] = []; for (let i = 0; i < n; i += stride) idx.push(i);
  if (n && idx[idx.length - 1] !== n - 1) idx.push(n - 1);
  return idx.slice(0, MAX_POINTS).map((i) => { const q = a[i];
    if (Array.isArray(q)) return { x: num(q[0], i), y: num(q[1], 0) };
    if (isObj(q)) return { x: num(q.x, i), y: num(q.y ?? q.value, 0) };
    return { x: i, y: num(q, 0) }; });
};
const readSeries = (p: Record<string, any>): Ser[] => {
  const s = Array.isArray(p.series) ? p.series : null;
  if (s && s.length) return s.slice(0, MAX_SERIES).map((q: any) => ({ name: String(isObj(q) ? q.name ?? "" : ""), pts: readPts(tryJson(Array.isArray(q) ? q : isObj(q) ? q.points : [])) }));
  return [{ name: "", pts: readPts(p.points) }];
};
function lineAxis(series: Ser[], p: Record<string, any>) {
  const xs = series.flatMap((s) => s.pts.map((q) => q.x)), ys = series.flatMap((s) => s.pts.map((q) => q.y));
  const mn = (a: number[], d: number) => (a.length ? a.reduce((u, v) => Math.min(u, v)) : d), mx = (a: number[], d: number) => (a.length ? a.reduce((u, v) => Math.max(u, v)) : d);
  let xmin = mn(xs, 0), xmax = mx(xs, 1); if (!(xmax > xmin)) xmax = xmin + 1;
  const lo = mn(ys, 0), hi = mx(ys, 1); const pad = (hi - lo || 1) * 0.1;
  // default: start at 0 when the data is non-negative and not hugging the top, else pad the data range
  let ymin = has(p.y_min) ? num(p.y_min, lo) : lo >= 0 && lo <= hi * 0.5 ? 0 : lo - pad;
  let ymax = has(p.y_max) ? num(p.y_max, NaN) : NaN; if (!Number.isFinite(ymax)) ymax = hi + pad;
  if (!(ymax > ymin)) ymax = ymin + (Math.abs(ymin) || 1);
  return { xmin, xmax, ymin, ymax };
}

const LineSvg = ({ theme, p, prev, m, pIn, W, H, continued }: Common) => {
  const series = readSeries(p); const ca = lineAxis(series, p);
  const pseries = prev ? readSeries(prev) : []; const pa = prev ? lineAxis(pseries, prev) : ca;
  const xmin = lerp(pa.xmin, ca.xmin, m), xmax = lerp(pa.xmax, ca.xmax, m), ymin = lerp(pa.ymin, ca.ymin, m), ymax = lerp(pa.ymax, ca.ymax, m);
  const muted = theme.palette.muted ?? theme.palette.fg;
  const title = has(p.title) ? String(p.title) : "";
  const labels: string[] = Array.isArray(p.x_labels) ? p.x_labels.slice(0, MAX_TICKS).map(String) : [];
  const multi = series.length > 1;
  const L = 130, R = 50, T = title ? (multi ? 150 : 110) : multi ? 90 : 50, B = 100; const x1 = W - R, top = T, bottom = H - B;
  const sx = (x: number) => L + ((x - xmin) / (xmax - xmin)) * (x1 - L);
  const sy = (y: number) => Math.max(top, Math.min(bottom, bottom - ((y - ymin) / (ymax - ymin)) * (bottom - top)));
  const axisOp = continued ? 1 : c01(pIn * 3);
  const draw = continued ? 1 : c01((pIn - 0.15) / 0.85);
  const yt = niceTicks(ymin, ymax, 5); const ydec = decOf(yt.step);
  const first = series[0]?.pts ?? [];
  let xticks: { x: number; t: string }[];
  if (labels.length) xticks = labels.map((t, i) => ({ t, x: labels.length === first.length ? first[i].x : labels.length === 1 ? (xmin + xmax) / 2 : xmin + (i / (labels.length - 1)) * (xmax - xmin) }));
  else { const xt = niceTicks(xmin, xmax, 6); const d = decOf(xt.step); xticks = xt.ticks.map((v) => ({ x: v, t: fmtVal(v, d) })); }
  const xfs = xticks.length > 8 ? 22 : 28;
  const cols = [theme.palette.accent, theme.palette.accent2, (theme.palette as any).accent3 ?? theme.palette.fg, theme.palette.fg, muted, theme.palette.accent];
  const hr: number[] | null = Array.isArray(p.highlight_range) && p.highlight_range.length === 2 ? p.highlight_range : null;
  const phr: number[] | null = prev && Array.isArray(prev.highlight_range) && prev.highlight_range.length === 2 ? prev.highlight_range : null;
  const hx0 = hr ? (phr && continued ? lerp(phr[0], hr[0], m) : hr[0]) : phr ? phr[0] : 0;
  const hx1 = hr ? (phr && continued ? lerp(phr[1], hr[1], m) : hr[1]) : phr ? phr[1] : 0;
  const hOp = hr ? (phr || !continued ? (continued ? 1 : c01((pIn - 0.5) * 2)) : m) : phr && continued ? 1 - m : 0;
  const clampX = (v: number) => Math.max(L, Math.min(x1, sx(v)));
  return <svg width={W} height={H} style={{ overflow: "visible" }}>
    {title && <text x={W / 2} y={60} textAnchor="middle" fontSize={46} fill={theme.palette.fg} opacity={axisOp}>{title}</text>}
    {multi && <g opacity={axisOp}>{series.map((s, i) => <text key={i} x={W / 2 + (i - (series.length - 1) / 2) * 280} y={title ? 112 : 56} textAnchor="middle" fontSize={32} fontWeight={700} fill={cols[i]}>{"● "}{clip(s.name || `series ${i + 1}`, 18)}</text>)}</g>}
    <g opacity={axisOp}>
      {yt.ticks.map((v, k) => <g key={"g" + k}><line x1={L} y1={sy(v)} x2={x1} y2={sy(v)} stroke={muted} strokeOpacity={0.14} strokeWidth={1} />
        <text x={L - 16} y={sy(v) + 10} textAnchor="end" fontSize={28} fill={muted} fillOpacity={0.9}>{fmtVal(v, ydec)}</text></g>)}
      <line x1={L} y1={top} x2={L} y2={bottom} stroke={muted} strokeOpacity={0.5} strokeWidth={3} />
      <line x1={L} y1={bottom} x2={x1} y2={bottom} stroke={muted} strokeOpacity={0.5} strokeWidth={3} />
      {xticks.map((q, k) => { const X = sx(q.x); if (X < L - 1 || X > x1 + 1) return null;
        return <g key={"x" + k}><line x1={X} y1={bottom} x2={X} y2={bottom + 8} stroke={muted} strokeOpacity={0.6} strokeWidth={2} />
          <text x={X} y={bottom + 12 + xfs} textAnchor="middle" fontSize={xfs} fill={muted} fillOpacity={0.9}>{clip(q.t, 12)}</text></g>; })}
    </g>
    {hOp > 0.01 && Math.abs(hx1 - hx0) > 0 && <g opacity={hOp}>
      <rect x={Math.min(clampX(hx0), clampX(hx1))} y={top} width={Math.abs(clampX(hx1) - clampX(hx0))} height={bottom - top} fill={theme.palette.accent2} fillOpacity={0.16} />
      <line x1={clampX(hx0)} y1={top} x2={clampX(hx0)} y2={bottom} stroke={theme.palette.accent2} strokeWidth={3} strokeDasharray="10 8" />
      <line x1={clampX(hx1)} y1={top} x2={clampX(hx1)} y2={bottom} stroke={theme.palette.accent2} strokeWidth={3} strokeDasharray="10 8" />
    </g>}
    {series.map((s, si) => {
      const ps = pseries[si]?.pts ?? [];
      const pts = s.pts.map((q, i) => { const o = continued && prev ? ps[i] : undefined; return o ? { x: lerp(o.x, q.x, m), y: lerp(o.y, q.y, m) } : q; });
      if (pts.length < 1) return null;
      const d = pts.map((q, i) => `${i ? "L" : "M"} ${sx(q.x).toFixed(1)} ${sy(q.y).toFixed(1)}`).join(" ");
      const last = pts[pts.length - 1];
      return <g key={si}>
        <path d={d} pathLength={1} strokeDasharray={`${draw} 1.001`} fill="none" stroke={cols[si]} strokeWidth={7} strokeLinecap="round" strokeLinejoin="round" />
        {pts.length <= 24 && pts.map((q, i) => <circle key={i} cx={sx(q.x)} cy={sy(q.y)} r={9} fill={cols[si]} opacity={c01(draw * pts.length - i)} />)}
        {pts.length > 24 && <circle cx={sx(last.x)} cy={sy(last.y)} r={11} fill={cols[si]} opacity={draw >= 1 ? 1 : 0} />}
      </g>;
    })}
  </svg>;
};

/** Shared hooks: `m` morphs prev props to current props (continued shots); `pIn` is the first-appearance build. */
const useChartAnim = (theme: Theme, continued: boolean, prev: any, delay = 0) => {
  const morph = useReveal(theme, 0.7); const build = useReveal(theme, 1.4, delay);
  return { m: continued && prev ? c01(morph) : 1, pIn: continued ? 1 : Math.max(0, build) };
};

const BarChart = ({ theme, prev, continued, ...p }: P) => {
  const { m, pIn } = useChartAnim(theme, !!continued, prev);
  return <Center><BarSvg theme={theme} p={p} prev={prev} m={m} pIn={pIn} W={1500} H={820} continued={!!continued} /></Center>;
};
const LineChart = ({ theme, prev, continued, ...p }: P) => {
  const { m, pIn } = useChartAnim(theme, !!continued, prev);
  return <Center><LineSvg theme={theme} p={p} prev={prev} m={m} pIn={pIn} W={1500} H={820} continued={!!continued} /></Center>;
};

const isLine = (c: Record<string, any>) => c.kind === "line" || c.type === "line_chart" || c.type === "line" || (!Array.isArray(c.bars) && (Array.isArray(c.points) || Array.isArray(c.series)));
const CompareSplit = ({ theme, left, right, verdict, prev, continued }: P) => {
  const l = coerceProps(left ?? {}), r = coerceProps(right ?? {});
  const lc = coerceProps(l.chart ?? {}), rc = coerceProps(r.chart ?? {});
  const pl = isObj(prev?.left) ? coerceProps(prev.left) : undefined, pr = isObj(prev?.right) ? coerceProps(prev.right) : undefined;
  const plc = pl ? coerceProps(pl.chart ?? {}) : undefined, prc = pr ? coerceProps(pr.chart ?? {}) : undefined;
  const a = useChartAnim(theme, !!continued, prev, 0), b = useChartAnim(theme, !!continued, prev, 0.6);
  const tl = useReveal(theme, 0.6), tr = useReveal(theme, 0.6, continued ? 0 : 0.6), tv = useReveal(theme, 0.8, continued ? 0 : 1.8);
  const W = 900, H = 640, ca = !!continued;
  const col = (title: any, chart: Record<string, any>, pc: Record<string, any> | undefined, an: { m: number; pIn: number }, tp: number, color: string) => (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", minWidth: 0 }}>
      <div style={{ fontSize: 52, fontWeight: 700, color, opacity: ca ? 1 : c01(tp), marginBottom: 6 }}>{has(title) ? String(title) : ""}</div>
      <div style={{ width: 860 }}>
        <svg viewBox={`0 0 ${W} ${H}`} width={860} height={860 * H / W} style={{ overflow: "visible" }}>
          {isLine(chart) ? <LineSvg theme={theme} p={chart} prev={pc} m={an.m} pIn={an.pIn} W={W} H={H} continued={ca} />
            : <BarSvg theme={theme} p={chart} prev={pc} m={an.m} pIn={an.pIn} W={W} H={H} continued={ca} />}
        </svg>
      </div>
    </div>);
  return <AbsoluteFill style={{ padding: "90px 50px 60px", flexDirection: "column", justifyContent: "center" }}>
    <div style={{ display: "flex", gap: 40, alignItems: "flex-start", justifyContent: "center" }}>
      {col(l.title, lc, plc, a, tl, theme.palette.accent2)}
      <div style={{ width: 2, alignSelf: "stretch", background: theme.palette.muted ?? theme.palette.fg, opacity: 0.25 }} />
      {col(r.title, rc, prc, b, tr, theme.palette.accent)}
    </div>
    {has(verdict) && <div style={{ textAlign: "center", fontSize: 58, marginTop: 30, color: theme.palette.fg, opacity: ca ? 1 : c01(tv), transform: `translateY(${ca ? 0 : (1 - c01(tv)) * 20}px)` }}>{String(verdict)}</div>}
  </AbsoluteFill>;
};

const decCount = (v: any) => { const m = String(v ?? "").replace(/,/g, "").match(/\.(\d+)/); return m ? m[1].length : 0; };
const StatReveal = ({ theme, value, unit, caption, from }: P) => {
  const p = c01(useReveal(theme, 1.6)); const pc = useReveal(theme, 0.7, 0.9);
  const target = num(value, 0), start = num(from, 0); const dec = Math.min(3, Math.max(decCount(value), decCount(from)));
  const sfx = typeof value === "string" ? value.trim().match(/^[-+]?[\d.,]+\s*(.*)$/)?.[1] ?? "" : "";
  const u = has(unit) ? String(unit) : sfx;
  const shown = fmtVal(lerp(start, target, p), dec);
  return <Center><div style={{ transform: `scale(${0.92 + 0.08 * p})` }}>
    <div style={{ fontSize: 280, fontWeight: 700, lineHeight: 1, color: theme.palette.accent }}>{shown}
      {u && <span style={{ fontSize: u.length <= 2 ? 200 : 100, marginLeft: u.length <= 2 ? 6 : 24, color: theme.palette.fg }}>{u}</span>}</div>
    {has(caption) && <div style={{ fontSize: 56, marginTop: 40, maxWidth: 1400, lineHeight: 1.3, opacity: c01(pc), transform: `translateY(${(1 - c01(pc)) * 20}px)` }}>{String(caption)}</div>}
  </div></Center>;
};

export const TEMPLATES: Record<string, React.FC<any>> = {
  title_card: TitleCard, callout: Callout, bullet_build: BulletBuild, misconception: Misconception, whiteboard_write: WhiteboardWrite,
  equation: Equation, equation_morph: EquationMorph, plot: Plot, number_line: NumberLine, diagram_nodes: DiagramNodes,
  bar_chart: BarChart, line_chart: LineChart, compare_split: CompareSplit, stat_reveal: StatReveal,
};
for (const k of Object.keys(TEMPLATES)) TEMPLATES[k] = safe(TEMPLATES[k]);
