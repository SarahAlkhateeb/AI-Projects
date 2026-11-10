import { Composition, staticFile, CalculateMetadataFunction } from "remotion";
import { Lesson } from "./Lesson";
import type { Storyboard } from "./types";

const calc: CalculateMetadataFunction<{ sb: Storyboard | null }> = async () => {
  const sb: Storyboard = await fetch(staticFile("storyboard.json")).then((r) => r.json());
  const fps = sb.fps || 30;
  const frames = sb.beats.reduce((n, b) => n + Math.round(b.duration_s * fps), 0);
  return { props: { sb }, fps, durationInFrames: Math.max(frames, fps) };
};

export const Root = () => (
  <Composition id="Lesson" component={Lesson} width={1920} height={1080} fps={30} durationInFrames={300}
    defaultProps={{ sb: null }} calculateMetadata={calc} />
);
