import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig, useCurrentFrame, interpolate } from "remotion";
import type { Storyboard, Shot, Theme } from "./types";
import { TEMPLATES, coerceProps } from "./templates";

/** Slow camera drift so no frame is ever static. Seeded per shot so each moves differently. */
const Camera = ({ theme, seed, frames, children }: { theme: Theme; seed: number; frames: number; children: React.ReactNode }) => {
  const f = useCurrentFrame();
  const mode = theme.motion.camera ?? "drift";
  if (mode === "none") return <AbsoluteFill>{children}</AbsoluteFill>;
  const amt = mode === "push" ? 1 : 0.5;
  const dir = (seed % 2 === 0 ? 1 : -1);
  const scale = interpolate(f, [0, frames], [1, 1 + 0.06 * amt], { extrapolateRight: "clamp" });
  const x = interpolate(f, [0, frames], [0, 18 * amt * dir], { extrapolateRight: "clamp" });
  const y = interpolate(f, [0, frames], [0, 10 * amt * ((seed >> 1) % 2 === 0 ? 1 : -1)], { extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) scale(${scale})`, transformOrigin: "50% 50%" }}>{children}</AbsoluteFill>;
};

/** Cross-fade in/out at shot edges. Scene shots that continue into/from a neighbour skip the edge they share. */
const Fade = ({ frames, fadeIn = true, fadeOut = true, children }: { frames: number; fadeIn?: boolean; fadeOut?: boolean; children: React.ReactNode }) => {
  const f = useCurrentFrame(); const fade = 9;
  const o = interpolate(f, [0, fade, Math.max(fade + 1, frames - fade), frames], [fadeIn ? 0 : 1, 1, 1, fadeOut ? 0 : 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: o }}>{children}</AbsoluteFill>;
};

/** Templates that persist across consecutive shots: later shots get `continued` + the previous shot's props. */
const SCENE_TEMPLATES = ["plot", "diagram_nodes", "number_line", "bar_chart", "line_chart", "compare_split"];

export const Lesson = ({ sb }: { sb: Storyboard | null }) => {
  const { fps } = useVideoConfig();
  if (!sb) return null;
  let beatStart = 0; let seed = 0;
  const beatStartTotal = sb.beats.reduce((n, b) => n + Math.round(b.duration_s * fps), 0);
  return (
    <AbsoluteFill style={{ background: sb.theme.palette.bg, fontFamily: sb.theme.font.family, color: sb.theme.palette.fg }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 120% 90% at 50% 35%, ${sb.theme.palette.accent}14 0%, transparent 55%), radial-gradient(ellipse 140% 110% at 50% 50%, transparent 60%, #00000055 100%)` }} />
      {sb.beats.map((b) => {
        const from = beatStart; const dur = Math.round(b.duration_s * fps); beatStart += dur;
        const CHIP: Record<string, string> = { hook: "The puzzle", misconception: "Wait\u2026", concrete_example: "Worked example", visual: "Picture it", generalize: "The rule", reprise: "Back to the puzzle", caveat: "One subtlety", exercise: "Your turn", meta: "Behind the idea" };
        const chip = CHIP[b.beat];
        return (
          <Sequence key={b.i} from={from} durationInFrames={dur} name={`beat ${b.i} ${b.beat}`}>
            <Audio src={staticFile(b.audio)} />
            {chip && <div style={{ position: "absolute", top: 44, left: 56, zIndex: 5, fontSize: 30, letterSpacing: 1.5, textTransform: "uppercase", color: sb.theme.palette.accent, opacity: 0.85, borderLeft: `4px solid ${sb.theme.palette.accent}`, paddingLeft: 16 }}>{chip}</div>}
            <div style={{ position: "absolute", bottom: 0, left: 0, height: 5, width: `${(100 * (from + dur)) / beatStartTotal}%`, background: sb.theme.palette.accent, opacity: 0.5, zIndex: 5 }} />
            {b.shots.map((s: Shot, k) => {
              const sf = Math.round(s.start_s * fps); const sd = Math.max(1, Math.round((s.end_s - s.start_s) * fps));
              const Tpl = TEMPLATES[s.template] ?? TEMPLATES.callout; seed++;
              const prev = k > 0 ? b.shots[k - 1] : null;
              const nxt = k + 1 < b.shots.length ? b.shots[k + 1] : null;
              const continues = !!prev && prev.template === s.template && SCENE_TEMPLATES.includes(s.template);
              const continuesNext = !!nxt && nxt.template === s.template && SCENE_TEMPLATES.includes(s.template);
              return (
                <Sequence key={k} from={sf} durationInFrames={sd} name={`${s.template}`}>
                  <Camera theme={sb.theme} seed={seed} frames={sd}>
                    <Fade frames={sd} fadeIn={!continues} fadeOut={!continuesNext}>
                      {continues ? <Tpl {...coerceProps(s.props)} prevProps={prev!.props} theme={sb.theme} continued /> : <Tpl {...coerceProps(s.props)} theme={sb.theme} />}
                    </Fade>
                  </Camera>
                </Sequence>
              );
            })}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
