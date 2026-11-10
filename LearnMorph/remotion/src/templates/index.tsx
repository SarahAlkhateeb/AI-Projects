import React from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { AbsoluteFill } from "remotion";
import { useReveal } from "../motion";
import type { Theme } from "../types";

type P = { theme: Theme; continued?: boolean } & Record<string, any>;

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

export const TEMPLATES: Record<string, React.FC<any>> = {
  title_card: TitleCard, callout: Callout, bullet_build: BulletBuild, misconception: Misconception, whiteboard_write: WhiteboardWrite,
  equation: Equation, equation_morph: EquationMorph, plot: Plot, number_line: NumberLine, diagram_nodes: DiagramNodes,
};
