export type Theme = {
  palette: { bg: string; fg: string; accent: string; accent2: string; muted?: string };
  font: { family: string; math?: string };
  motion: { speed: "slow" | "medium" | "fast"; easing: "ease" | "spring" | "linear"; camera?: "none" | "drift" | "push"; shot_seconds?: [number, number]; signature?: string };
};
export type Shot = { start_s: number; end_s: number; template: string; props: Record<string, any> };
export type Beat = { i: number; beat: string; audio: string; duration_s: number; narration?: string; shots: Shot[] };
export type Storyboard = { teacher: string; fps: number; theme: Theme; beats: Beat[] };
