"""Stage — assemble per-scene video + per-scene narration into a synced MP4.

WHY this module replaces the old "one combined audio over concatenated video":
- That approach muxed a single 28.8s audio track over a 26.4s concatenated
  video: per-scene boundaries did not line up, narration drifted scene to scene,
  and the final ~2.4s of speech was cut off. The root cause was treating audio
  and video as two independently-timed streams.
- The fix: make each SCENE self-consistent first. For scene i, force the video
  clip duration to equal that scene's NARRATION duration, mux them together,
  THEN concat the already-synced per-scene MP4s. Drift cannot accumulate because
  every scene starts at 0 offset for both streams.

HOW we match durations (engine-agnostic, deterministic):
- If the rendered video is SHORTER than the narration, hold the last frame
  (tpad) so the final figure/equation rests on screen while the line finishes —
  natural for an explainer.
- If the video is LONGER, trim the trailing hold (the template ends on a wait/
  fade, so trimming the tail removes dead air, not content).
- We do NOT depend on any specific TTS engine: we only read measured audio
  durations (from learnmorph.narrate) and ffprobe the video clips.
"""

import subprocess
from pathlib import Path

SCENES_DIR = Path("outputs/scenes")


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def _stream_duration(path: Path, kind: str) -> float:
    """Duration of a specific stream ('v' or 'a'), else 0.0. WHY per-stream: a
    scene's sync truth is its video stream vs its audio stream, not the container
    format duration (which reports the longer of the two)."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            f"{kind}:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def fit_and_mux_scene(
    video: Path, audio: Path, target_seconds: float, out_path: Path, fps: int = 15
) -> Path:
    """Produce one scene MP4 whose VIDEO and AUDIO streams are BOTH exactly
    `target_seconds` (= the narration duration).

    WHY do fit + mux in ONE ffmpeg pass with explicit `-t` on both streams:
    - The earlier two-pass approach (pad video, then `-shortest` mux) left the
      video stream landing a few 15fps frames short of the audio, so per-scene
      and final A/V drifted (~0.2-0.3s) and speech was clipped.
    - Here we force determinism: pad the VIDEO past target with tpad (freeze the
      last frame, natural for an explainer), pad the AUDIO past target with apad
      (trailing silence), then cut BOTH at exactly `-t target_seconds`. Both
      streams therefore end on the same timestamp. No `-shortest`, no drift.

    WHY `fps` is a parameter: the re-encode must PRESERVE the render's frame
    rate. v3 rendered draft 480p15; the v4 quality sprint renders 1080p60 —
    hardcoding `-r 15` here would silently throw away the high-quality render.
    """
    video, audio, out_path = Path(video), Path(audio), Path(out_path)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        # Video: hold the last frame long enough to cover target, then -t cuts it.
        "-vf",
        "tpad=stop_mode=clone:stop_duration=4",
        # Audio: pad trailing silence so a slightly-short clip still reaches target.
        "-af",
        "apad",
        "-t",
        f"{target_seconds:.3f}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def assemble(
    scene_videos: list[Path],
    scene_audios: list[dict],
    final_path: Path,
    prefix: str = "v3",
    fps: int = 15,
) -> dict:
    """Build a synced final MP4 from per-scene videos + per-scene narration.

    Parameters
    ----------
    scene_videos : list[Path]
        Rendered (silent) per-scene MP4s, in order.
    scene_audios : list[dict]
        Per-scene audio dicts from learnmorph.narrate (each has "path",
        "duration"), in the SAME order as scene_videos.
    final_path : Path
        Where to write the final muxed+concatenated MP4.
    prefix : str
        Filename prefix for intermediates (v3_scene_01.mp4 etc.) so different
        builds don't clobber each other's intermediates.
    fps : int
        Frame rate to PRESERVE through the re-encode (must match the render).

    Returns
    -------
    dict with keys:
        path        -> Path to the final MP4
        per_scene   -> list of {"id?","video_dur","audio_dur","delta"} after fit
        final_video -> float duration of the final video stream
        final_audio -> float duration of the final audio stream
    """
    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    muxed: list[dict] = []
    per_scene: list[dict] = []
    for i, (vid, aud) in enumerate(zip(scene_videos, scene_audios, strict=True), start=1):
        target = aud["duration"]
        scene_mp4 = fit_and_mux_scene(
            vid, aud["path"], target, SCENES_DIR / f"{prefix}_scene_{i:02d}.mp4", fps=fps
        )
        muxed.append({"path": scene_mp4})
        # Measure the ACTUAL muxed scene's two streams — that is the truth that
        # ships, after the single-pass fit+mux forced both to `target_seconds`.
        vdur = _stream_duration(scene_mp4, "v")
        adur = _stream_duration(scene_mp4, "a")
        per_scene.append(
            {
                "id": aud.get("id", f"s{i:02d}"),
                "video_dur": round(vdur, 3),
                "audio_dur": round(adur, 3),
                "delta": round(abs(vdur - adur), 3),
            }
        )

    concat = SCENES_DIR / f"{prefix}_concat.txt"
    concat.write_text("".join(f"file '{m['path'].resolve()}'\n" for m in muxed))
    # Re-encode on concat so the joined stream has a single clean timebase.
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(final_path),
        ],
        check=True,
        capture_output=True,
    )

    # Final stream durations (probe video and audio separately).
    fv = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(final_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fa = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(final_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    return {
        "path": final_path,
        "per_scene": per_scene,
        "final_video": float(fv) if fv else _duration(final_path),
        "final_audio": float(fa) if fa else _duration(final_path),
    }
