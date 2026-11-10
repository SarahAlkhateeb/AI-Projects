"""Objective Phase-2 Definition-of-done verifier (exits non-zero on failure).

WHY a script and not a checklist in prose:
- The A/V desync bug shipped because the Definition of done was verified by eye,
  and "the video plays" hid the fact that audio and video drifted and speech was
  cut off. An objective, runnable gate makes that class of bug impossible to pass
  silently: if any check fails this exits 1, so `run.sh` / loop / CI stop.

Checks (all objective, no LLM):
1. Required modules + templates exist.
2. The profile has the enriched fields (style_descriptors, intent_sequence,
   exemplars with a verbatim transcript_snippet).
3. CLOSED LOOP: no hand-rolled 3b1b palette literals in the generation path.
4. The final video exists, has BOTH a video and an audio stream, and PASSES the
   A/V sync gate (|video_dur - audio_dur| < tol). <-- the desync gate.
"""

import json
import subprocess
import sys
from pathlib import Path

from learnmorph.eval_metrics import check_video_sync

ROOT = Path(__file__).resolve().parents[1]

_REQUIRED_MODULES = [
    "transcribe",
    "frames",
    "describe",
    "profile",
    "conditioning",
    "narrate",
    "assemble",
    "eval_metrics",
]
_REQUIRED_TEMPLATES = ["equation_transform.py", "area_model.py", "equation_step_through.py"]
# The hand-rolled 3b1b palette we removed; it must not reappear in the gen path.
_BANNED_LITERALS = ("0E1116", "FFD166", "0e1116", "ffd166")
_GEN_PATH = [
    "templates/equation_transform.py",
    "templates/area_model.py",
    "templates/equation_step_through.py",
    "learnmorph/conditioning.py",
    "learnmorph/generate_v2.py",
    "learnmorph/generate_v3.py",
    "learnmorph/generate_v4.py",
    "learnmorph/generate_v5.py",
    "learnmorph/narrate.py",
    "learnmorph/assemble.py",
]


def _expected_narration_seconds(final_video: Path) -> float | None:
    """Intended narration total from this build's MANIFEST (engine-aware).

    WHY a manifest, not a directory glob: the per-slug audio dir can contain BOTH
    engines' files at once (e.g. leftover `say` .aiff preview stand-ins beside the
    real ElevenLabs .mp3). Globbing + summing every clip double-counts the two
    engines and yields a bogus "expected narration" total, which then reports a
    false truncation failure even though the final demo is perfectly synced. The
    manifest, written by generate_v3, lists ONLY the per-scene audio THIS build
    actually muxed — so the expected total matches what shipped.

    Returns the manifest's intended_narration_seconds, or None if no manifest
    exists (caller then falls back to stream-vs-stream sync only).
    """
    manifest = final_video.with_suffix(".manifest.json")
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text())
    total = data.get("intended_narration_seconds")
    if total is None and data.get("scenes"):
        total = sum(float(s.get("duration", 0)) for s in data["scenes"])
    return float(total) if total else None


def verify(profile_path: Path, final_video: Path, tol: float = 0.15) -> dict:
    """Run all objective Phase-2 DoD checks. Returns {ok, checks, failures}."""
    checks: list[tuple[str, bool, str]] = []

    for m in _REQUIRED_MODULES:
        p = ROOT / "learnmorph" / f"{m}.py"
        checks.append((f"module learnmorph/{m}.py", p.exists(), str(p)))
    for t in _REQUIRED_TEMPLATES:
        p = ROOT / "templates" / t
        checks.append((f"template templates/{t}", p.exists(), str(p)))

    # Enriched profile fields.
    if Path(profile_path).exists():
        prof = json.loads(Path(profile_path).read_text())
        has_desc = bool(prof.get("style_descriptors"))
        has_intents = bool((prof.get("pedagogy") or {}).get("intent_sequence"))
        has_exemplars = any(e.get("transcript_snippet") for e in prof.get("exemplars", []))
        checks.append(("profile.style_descriptors", has_desc, ""))
        checks.append(("profile.pedagogy.intent_sequence", has_intents, ""))
        checks.append(("profile.exemplars[].transcript_snippet", has_exemplars, ""))
    else:
        checks.append(("profile exists", False, str(profile_path)))

    # Closed loop: no banned palette literals anywhere in the generation path.
    leaks: list[str] = []
    for rel in _GEN_PATH:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text()
        for lit in _BANNED_LITERALS:
            if lit in text:
                leaks.append(f"{rel}:{lit}")
    checks.append(("closed loop (no hand-rolled palette in gen path)", not leaks, "; ".join(leaks)))

    # Final video: exists, has both streams, passes the A/V sync gate.
    fv = Path(final_video)
    exists = fv.exists()
    checks.append((f"final video exists ({fv.name})", exists, str(fv)))
    if exists:
        streams = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(fv),
            ],
            capture_output=True,
            text=True,
        ).stdout
        has_v, has_a = "video" in streams, "audio" in streams
        checks.append(("final video has video stream", has_v, ""))
        checks.append(("final video has audio stream", has_a, ""))
        # Pass the INTENDED narration total so the gate also catches TRUNCATION
        # (lost speech), not just stream-vs-stream drift. We sum the per-scene
        # audio for this video's slug if those files are on disk.
        expected = _expected_narration_seconds(fv)
        sync = check_video_sync(fv, tol=tol, expected_audio=expected)
        detail = f"video={sync['video_dur']}s audio={sync['audio_dur']}s"
        if expected is not None:
            detail += (
                f" expected_narration={sync['expected_audio']}s trunc={sync['truncation_delta']}s"
            )
        checks.append((f"A/V sync (no drift, no truncation; tol={tol})", sync["ok"], detail))

        # NO-TRIM gate (Phase 3): the v4 chop shipped because 13.98s of rendered
        # animation was cut to 8.08s of audio and nothing measured the RAW render
        # against the narration. Beat builds record raw_render_seconds per beat
        # in the manifest; any beat losing more than the tolerance fails here.
        manifest_path = fv.with_suffix(".manifest.json")
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
            beats = data.get("beats") or []
            if beats:
                trim_tol = float(data.get("trim_tolerance_seconds", 0.25))
                over = [
                    f"{b['id']}: trim={b.get('trim_seconds', 0)}s"
                    for b in beats
                    if float(b.get("trim_seconds", 0)) > trim_tol
                ]
                checks.append(
                    (
                        f"no-trim (every beat's render fits its narration; tol={trim_tol}s)",
                        not over,
                        "; ".join(over),
                    )
                )

    failures = [name for name, ok, _ in checks if not ok]
    return {"ok": not failures, "checks": checks, "failures": failures}


def main() -> int:
    profile = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "outputs/profiles/WUvTyaaNkzM.json"
    # Newest-first: v5 beat build, v4 quality sprint, keyed v3, preview.
    candidates = [
        ROOT / "outputs/final/today_demo_v5.mp4",
        ROOT / "outputs/final/today_demo_v4.mp4",
        ROOT / "outputs/final/today_demo_v3.mp4",
        ROOT / "outputs/final/today_demo_v3_PREVIEW.mp4",
    ]
    default = next((c for c in candidates if c.exists()), candidates[0])
    final = Path(sys.argv[2]) if len(sys.argv) > 2 else default

    result = verify(profile, final)
    for name, ok, detail in result["checks"]:
        mark = "PASS" if ok else "FAIL"
        line = f"[{mark}] {name}"
        if not ok and detail:
            line += f"  -> {detail}"
        print(line)
    print("\nDoD:", "OK" if result["ok"] else f"FAILED ({len(result['failures'])} check(s))")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
