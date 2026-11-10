import { interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import type { Theme } from "./types";

const SPEED = { slow: 1.6, medium: 1.0, fast: 0.6 };

/** 0→1 progress over `seconds`, shaped by the theme's easing. */
export function useReveal(theme: Theme, seconds = 1, delaySec = 0) {
  const frame = useCurrentFrame(); const { fps } = useVideoConfig();
  const dur = seconds * SPEED[theme.motion.speed] * fps; const f = frame - delaySec * fps;
  if (theme.motion.easing === "spring") return spring({ frame: f, fps, config: { damping: 14, stiffness: 90 }, durationInFrames: dur });
  const easing = theme.motion.easing === "linear" ? Easing.linear : Easing.bezier(0.25, 0.1, 0.25, 1);
  return interpolate(f, [0, dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing });
}
