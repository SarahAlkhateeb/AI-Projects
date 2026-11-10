"""Cheap automated visual metric: appearance_style (source vs generated).

WHY a metric at all (Phase 2 eval upgrade):
- The Gemini judge scores subjective quality, but it is a single LLM opinion. A
  cheap, deterministic, automated number that says "does the generated video
  LOOK like the source" gives the pipeline an objective visual signal that does
  not drift between runs and costs nothing per call.

WHY a color-histogram cosine, not CLIP:
- The brief asks for "one cheap visual metric (CLIP cosine ... -> appearance_
  style)" and explicitly says keep it lightweight / optional if heavy. Real CLIP
  needs torch, and torch pins numpy<2 which COLLIDES with manim's numpy>=2 in
  this single venv (same reason transcribe.py uses faster-whisper, not openai-
  whisper). So we approximate appearance similarity with an HSV color-histogram
  cosine using cv2 (already a dependency). For 3b1b style transfer the dominant
  appearance signal IS the palette — dark bg, one bright primary, a sparse
  accent — which a color histogram captures directly. Same shape as a CLIP
  score: 0..1, higher = more alike. Swappable for CLIP later behind this API.

This module returns dicts with named keys (project convention) and never raises
on a single unreadable frame — a missing comparison degrades to a partial mean.
"""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

_HIST_BINS = (8, 8, 8)  # H, S, V buckets — coarse enough to be palette-robust


def _frame_hist(image_bgr: np.ndarray) -> np.ndarray:
    """Normalized HSV color histogram for one frame (flattened, L2-normalized)."""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, _HIST_BINS, [0, 180, 0, 256, 0, 256])
    vec = hist.flatten().astype(np.float64)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two already-normalized vectors, clamped to [0, 1]."""
    return float(max(0.0, min(1.0, float(np.dot(a, b)))))


def extract_midframe(video_path: Path, out_path: Path) -> Path:
    """Grab a representative frame (~40% in) from a video via ffmpeg.

    WHY ~40% and not the first frame: the opening frame is often a fade-in from
    the background color and is not representative of the on-screen content.
    """
    video_path, out_path = Path(video_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Probe duration so we can seek to a fractional point.
    dur = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    seek = max(0.0, float(dur) * 0.4) if dur else 1.0
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(seek), "-i", str(video_path), "-frames:v", "1", str(out_path)],
        check=True,
        capture_output=True,
    )
    return out_path


def appearance_style(generated_frame: Path, source_frames: list[Path]) -> dict:
    """Appearance similarity of a generated frame vs the source-video frames.

    Parameters
    ----------
    generated_frame : Path
        A frame extracted from the generated video (e.g. today_demo_v2.mp4).
    source_frames : list[Path]
        The sampled source frames (outputs/frames/<id>/*.jpg).

    Returns
    -------
    dict with keys:
        appearance_style -> float 0..1, mean histogram cosine vs all source
                            frames (higher = generated look matches source).
        best_match       -> float 0..1, the single closest source frame.
        n_compared       -> int, how many source frames were usable.
    """
    gen = cv2.imread(str(generated_frame))
    if gen is None:
        return {"appearance_style": 0.0, "best_match": 0.0, "n_compared": 0}
    gen_hist = _frame_hist(gen)

    sims: list[float] = []
    for sf in source_frames:
        img = cv2.imread(str(sf))
        if img is None:
            continue
        sims.append(_cosine(gen_hist, _frame_hist(img)))

    if not sims:
        return {"appearance_style": 0.0, "best_match": 0.0, "n_compared": 0}
    return {
        "appearance_style": round(sum(sims) / len(sims), 4),
        "best_match": round(max(sims), 4),
        "n_compared": len(sims),
    }


def _stream_duration(video_path: Path, kind: str) -> float:
    """Duration of a specific stream ('v' or 'a') via ffprobe, else 0.0."""
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
            str(video_path),
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def av_sync(
    per_scene: list[dict], final_video: float, final_audio: float, tol: float = 0.15
) -> dict:
    """Objective A/V sync gate. This is the check that the desync bug must fail.

    WHY this exists: the Phase-2 desync (combined audio over mismatched video,
    speech cut off) silently passed the old Definition of done because nothing
    compared per-scene durations. This makes that class of bug impossible to ship
    unnoticed: every scene must have |video_dur - audio_dur| < tol, and the final
    video and audio stream durations must agree within tol.

    Parameters
    ----------
    per_scene : list[dict]
        From learnmorph.assemble.assemble()["per_scene"]; each has video_dur,
        audio_dur, delta.
    final_video, final_audio : float
        Final stream durations from assemble().
    tol : float
        Max allowed per-scene and final mismatch in seconds (default 0.15).

    Returns
    -------
    dict with keys:
        ok            -> bool, True iff every check passed
        max_scene_delta -> float, worst per-scene |v-a|
        final_delta   -> float, |final_video - final_audio|
        failures      -> list[str], human-readable failing checks
    """
    failures: list[str] = []
    max_delta = 0.0
    for s in per_scene:
        d = float(s.get("delta", abs(s.get("video_dur", 0) - s.get("audio_dur", 0))))
        max_delta = max(max_delta, d)
        if d >= tol:
            failures.append(
                f"{s.get('id', '?')}: |video {s.get('video_dur')} - audio {s.get('audio_dur')}| = {d:.3f} >= {tol}"
            )
    final_delta = abs(final_video - final_audio)
    if final_delta >= tol:
        failures.append(
            f"final: |video {final_video:.3f} - audio {final_audio:.3f}| = {final_delta:.3f} >= {tol}"
        )
    return {
        "ok": not failures,
        "max_scene_delta": round(max_delta, 3),
        "final_delta": round(final_delta, 3),
        "failures": failures,
    }


def check_video_sync(
    video_path: Path, tol: float = 0.15, expected_audio: float | None = None
) -> dict:
    """Standalone sync check on a finished MP4: compare its v and a streams.

    Used in the Definition-of-done verification — a finished file whose video and
    audio stream durations disagree by >= tol fails the gate.

    WHY `expected_audio`: comparing only the file's OWN two streams cannot detect
    TRUNCATION. The original desync bug muxed a 28.8s narration over a 26.4s video
    with `-shortest`, which CUT the audio to 26.4s — so the file's streams agreed
    (both 26.4s) and a stream-vs-stream check passed while ~2.4s of speech was
    silently lost. Passing the INTENDED narration total (sum of per-scene audio)
    lets the gate also catch lost speech: |video_dur - expected_audio| must be
    < tol too. Callers that know the intended narration length should pass it.
    """
    video_path = Path(video_path)
    v = _stream_duration(video_path, "v")
    a = _stream_duration(video_path, "a")
    delta = abs(v - a)
    if expected_audio is not None:
        trunc = abs(v - expected_audio)
        return {
            "ok": delta < tol and trunc < tol,
            "video_dur": round(v, 3),
            "audio_dur": round(a, 3),
            "delta": round(delta, 3),
            "expected_audio": round(expected_audio, 3),
            "truncation_delta": round(trunc, 3),
        }
    return {
        "ok": delta < tol,
        "video_dur": round(v, 3),
        "audio_dur": round(a, 3),
        "delta": round(delta, 3),
    }


def score_video_appearance(video_path: Path, source_frame_dir: Path) -> dict:
    """Convenience: extract a midframe from a video and score it vs source frames.

    Returns the appearance_style dict plus the extracted frame path.
    """
    video_path = Path(video_path)
    mid = extract_midframe(video_path, video_path.with_suffix(".midframe.jpg"))
    source_frames = sorted(Path(source_frame_dir).glob("*.jpg"))
    result = appearance_style(mid, source_frames)
    result["generated_frame"] = str(mid)
    return result


if __name__ == "__main__":
    video = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/final/today_demo_v2.mp4")
    frames = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("outputs/frames/WUvTyaaNkzM")
    print(score_video_appearance(video, frames))
