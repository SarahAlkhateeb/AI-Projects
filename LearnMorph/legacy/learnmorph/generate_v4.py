"""Phase-2 quality sprint: profile + v4 script -> today_demo_v4.mp4.

WHY v4 (three verified complaints from review -> three fixes):
1. "Animation is not good quality"  -> scenes rendered at 1080p60 (-qh) instead
   of the 480p15 draft flag, plus eased rate functions and slightly longer
   post-punchline holds in the templates.
2. "Voice not matching the slide"   -> WITHIN-scene beat alignment: after
   synthesizing each scene's narration we run Whisper (local, free) on OUR OWN
   generated audio, find the scene's ANCHOR word, and schedule the key
   animation (morph / corner-fill) to START when that word is spoken via the
   templates' anchor_offset_seconds slot. Deterministic, no LLM in the loop.
3. "Tone is boring, not human"      -> v4 script written with the profile's
   exemplars as few-shot (20-24 words/scene, rhetorical warmth) and contextual
   ElevenLabs tone tags per scene.

Engine policy: ElevenLabs ONLY. If the key/SDK is missing or the API errors,
this generator STOPS LOUDLY (exit 2) — it never silently falls back to `say`,
because a robotic stand-in shipping as the "final" is exactly the trap that
produced the bad review.

Run from project root:
    uv run python -m learnmorph.generate_v4
"""

import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from learnmorph.assemble import assemble
from learnmorph.conditioning import condition
from learnmorph.eval_metrics import av_sync
from learnmorph.generate_v2 import _render_env, _split_value, _style_slots
from learnmorph.narrate import elevenlabs_available, narrate

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "outputs" / "profiles" / "WUvTyaaNkzM.json"
SCRIPT = ROOT / "outputs" / "scripts" / "completing_square_v4.json"
SCENES_DIR = ROOT / "outputs" / "scenes"
FINAL = ROOT / "outputs" / "final" / "today_demo_v4.mp4"

# Render-quality modes. -qh = 1920x1080@60. The fallback keeps 1080 lines but
# halves the frame rate if a scene render exceeds the tolerable wall-clock cap.
_RENDER_CAP_SECONDS = 300
_MODES = {
    "1080p60": {"flags": ["-qh"], "subdir": "1080p60", "fps": 60},
    "1080p30": {"flags": ["--resolution", "1920,1080", "--fps", "30"], "subdir": "1080p30", "fps": 30},
}

_DRIVER_HEADER = '''"""Generated v4 driver — DO NOT hand-edit.

Content slots from outputs/scripts/completing_square_v4.json. Style + timing
slots from outputs/profiles/WUvTyaaNkzM.json via learnmorph.conditioning.
anchor_offset_seconds from Whisper word timestamps on THIS build's narration.
"""
'''


def _norm(token: str) -> str:
    """Lowercase a word and strip punctuation, for anchor matching."""
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _word_times(audio_path: Path, model) -> list[dict]:
    """Word-level timestamps for one narration clip via faster-whisper.

    WHY on our OWN audio: the TTS engine decides the real cadence; the script's
    word order alone can't tell us when a word lands. Whisper on the generated
    clip gives ground-truth times, locally and for free.
    """
    segments, _info = model.transcribe(str(audio_path), word_timestamps=True)
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"word": _norm(w.word), "start": round(float(w.start), 3)})
    return words


def _anchor_time(words: list[dict], anchor_word: str) -> float | None:
    """First spoken time of the anchor word, or None if Whisper missed it."""
    target = _norm(anchor_word)
    if not target:
        return None
    for w in words:
        if w["word"] == target:
            return w["start"]
    # Fallback: substring match (Whisper sometimes glues punctuation/plurals).
    for w in words:
        if target in w["word"] or w["word"] in target:
            return w["start"]
    return None


def write_driver(
    idx: int, scene: dict, visual: dict, anchor_offset: float, post_scale: float = 1.0
) -> Path:
    """Emit a v4 driver: template by intent, style from profile, anchor +
    post-anchor scale from Whisper timing. Same template-constrained discipline
    as v2/v3."""
    vh = scene["visual_hint"]
    intent = scene.get("intent", "")
    cls = f"V4Scene{idx:02d}"

    if "geometr" in intent:
        content = (
            "\nfrom templates.area_model import AreaModel\n\n\n"
            + f"class {cls}(AreaModel):\n"
            + '    side_label = r"x"\n'
            + f'    split_value = r"{_split_value(vh["equation_from"])}"\n'
        )
    else:
        content = (
            "\nfrom templates.equation_transform import EquationTransform\n\n\n"
            + f"class {cls}(EquationTransform):\n"
            + f'    equation_a = r"{vh["equation_from"]}"\n'
            + f'    equation_b = r"{vh["equation_to"]}"\n'
        )

    body = (
        _DRIVER_HEADER
        + content
        + f'    caption_text = "{vh["caption"]}"\n'
        + f"    anchor_offset_seconds = {anchor_offset:.3f}\n"
        + f"    post_anchor_scale = {post_scale:.3f}\n"
        + _style_slots(visual)
        + "\n"
    )
    path = SCENES_DIR / f"v4_scene_{idx:02d}.py"
    path.write_text(body)
    return path


def _driver_probe(driver: Path, cls_name: str):
    """Import a generated driver fresh and return a LIGHTWEIGHT probe instance.

    WHY object.__new__: we need to call the template's timing methods
    (anchor_lead_in / post_anchor_natural), which read class attributes and call
    each other — so they need a real bound `self`. But running Scene.__init__
    would spin up manim's camera/renderer machinery just to do arithmetic.
    object.__new__ allocates the instance without __init__: attribute lookups
    fall back to the class slots, methods bind normally, nothing renders.
    """
    spec = importlib.util.spec_from_file_location(driver.stem, driver)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, cls_name)
    return object.__new__(cls)


def fit_scene_to_audio(
    idx: int, scene: dict, visual: dict, anchor_time: float | None, audio_dur: float
) -> tuple[Path, float]:
    """Write the FINAL driver for a scene, timed to its narration.

    Two-pass, using the TEMPLATE's own beat arithmetic (anchor_lead_in /
    post_anchor_natural) as the single source of truth:
      pass 1: write with neutral scale, import, read the effective lead-in and
              the natural post-anchor length;
      pass 2: compute post_anchor_scale so anchor_start + post-anchor animation
              fits inside audio_dur (clamped 0.3-1.2 to stay watchable), then
              rewrite the driver with the final values.

    WHY: v3 trimmed over-long scenes mid-animation — THAT is what "voice not
    matching the slide" looks like. Fitting the timeline to the narration means
    the assembler only ever pads a short freeze tail, never cuts a moving beat.

    Returns (driver_path, predicted_anchor_start).
    """
    cls_name = f"V4Scene{idx:02d}"
    offset = anchor_time if anchor_time is not None else 0.0

    driver = write_driver(idx, scene, visual, offset, post_scale=1.0)
    probe = _driver_probe(driver, cls_name)
    lead_in = probe.anchor_lead_in()
    post_natural = probe.post_anchor_natural()
    anchor_start = max(lead_in, offset)

    budget = audio_dur - anchor_start - 0.15  # small tail margin for the fade
    scale = max(0.3, min(1.2, budget / post_natural)) if post_natural > 0 else 1.0

    driver = write_driver(idx, scene, visual, offset, post_scale=scale)
    probe = _driver_probe(driver, cls_name)
    predicted = max(probe.anchor_lead_in(), offset)
    return driver, predicted


def render(driver: Path, idx: int, mode: str) -> tuple[Path, float]:
    """Render one driver at the given quality mode; returns (mp4, seconds)."""
    cls = f"V4Scene{idx:02d}"
    cfg = _MODES[mode]
    rel = driver.relative_to(ROOT)
    t0 = time.monotonic()
    subprocess.run(
        [sys.executable, "-m", "manim", *cfg["flags"], str(rel), cls],
        cwd=ROOT,
        check=True,
        env=_render_env(),
    )
    elapsed = time.monotonic() - t0
    src = ROOT / "media" / "videos" / driver.stem / cfg["subdir"] / f"{cls}.mp4"
    # NB: name must NOT collide with the assembler's muxed outputs
    # (v4_scene_NN.mp4) — ffmpeg reading and writing the same path corrupts the
    # file. Raw renders therefore go to v4_raw_NN.mp4.
    dst = SCENES_DIR / f"v4_raw_{idx:02d}.mp4"
    dst.write_bytes(src.read_bytes())
    return dst, elapsed


def main() -> dict:
    # Engine gate FIRST: ElevenLabs only, fail loud, never a silent say-fallback.
    if not elevenlabs_available():
        print("FATAL: ElevenLabs unavailable (key or SDK missing). Refusing to fall back to `say`.")
        sys.exit(2)

    params = condition(PROFILE)
    visual = params["visual"]
    script = json.loads(SCRIPT.read_text())

    # 1) Narrate FIRST (the audio cadence is the ground truth everything else
    #    aligns to). If this script's per-scene MP3s already exist on disk we
    #    REUSE them — repeat runs (e.g. after a downstream assembly bug) must
    #    not re-spend ElevenLabs characters for identical audio. Delete
    #    outputs/audio/completing_square_v4/ to force re-synthesis after a
    #    script text change. Any API error surfaces verbatim — no fallback.
    audio_dir = ROOT / "outputs" / "audio" / "completing_square_v4"
    cached = [audio_dir / f"{s['id']}.mp3" for s in script["scenes"]]
    if all(p.exists() for p in cached):
        durs = [
            float(
                subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(p)],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()
            )
            for p in cached
        ]
        spoken = {
            "engine": "elevenlabs",
            "slug": "completing_square_v4",
            "scenes": [
                {"id": s["id"], "path": p, "duration": round(d, 3)}
                for s, p, d in zip(script["scenes"], cached, durs, strict=True)
            ],
            "total_seconds": round(sum(durs), 3),
        }
        print("narration: REUSING existing ElevenLabs clips (no characters spent)")
    else:
        try:
            spoken = narrate(SCRIPT, PROFILE, slug="completing_square_v4")
        except Exception as exc:  # surface exact 401/402/etc. and stop
            print(f"FATAL: ElevenLabs narration failed: {exc!r}")
            sys.exit(2)
        if spoken["engine"] != "elevenlabs":
            print(f"FATAL: expected engine=elevenlabs, got {spoken['engine']}. Aborting.")
            sys.exit(2)
    print(f"narration engine = {spoken['engine']} (total {spoken['total_seconds']}s)")

    # 2) Whisper word timestamps on our own narration -> per-scene anchor times.
    from faster_whisper import WhisperModel

    whisper = WhisperModel("base", device="cpu", compute_type="int8")
    anchors: list[dict] = []
    for scene, aud in zip(script["scenes"], spoken["scenes"], strict=True):
        words = _word_times(Path(aud["path"]), whisper)
        t = _anchor_time(words, scene.get("anchor_word", ""))
        anchors.append({"id": scene["id"], "word": scene.get("anchor_word", ""), "time": t})
        print(f"  anchor {scene['id']}: '{scene.get('anchor_word')}' spoken at {t}s")

    # 3) Drivers timed to the narration (anchor + post-anchor scale) + 1080p
    #    renders (adaptive fps fallback if a render is intolerably slow).
    mode = "1080p60"
    scene_videos: list[Path] = []
    anchor_report: list[dict] = []
    for i, (scene, anc, aud) in enumerate(
        zip(script["scenes"], anchors, spoken["scenes"], strict=True), start=1
    ):
        driver, start = fit_scene_to_audio(i, scene, visual, anc["time"], float(aud["duration"]))
        delta = None if anc["time"] is None else round(start - anc["time"], 3)
        anchor_report.append({**anc, "anim_start": round(start, 3), "delta": delta})

        mp4, secs = render(driver, i, mode)
        print(f"  rendered scene {i} [{mode}] in {secs:.0f}s")
        if secs > _RENDER_CAP_SECONDS and mode == "1080p60":
            mode = "1080p30"
            print(f"  render exceeded {_RENDER_CAP_SECONDS}s -> remaining scenes at 1080p30")
        scene_videos.append(mp4)

    # 4) Assemble (sync-correct, per-scene fit+mux) at the render frame rate.
    fps = _MODES[mode]["fps"]
    result = assemble(scene_videos, spoken["scenes"], FINAL, prefix="v4", fps=fps)

    # 5) Manifest: the EXACT audio this build muxed (verify_dod reads this).
    manifest = {
        "engine": spoken["engine"],
        "final_video": str(FINAL),
        "render_mode": mode,
        "scenes": [
            {"id": s["id"], "audio": str(s["path"]), "duration": round(float(s["duration"]), 3)}
            for s in spoken["scenes"]
        ],
        "intended_narration_seconds": round(sum(float(s["duration"]) for s in spoken["scenes"]), 3),
        "anchors": anchor_report,
    }
    FINAL.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))

    # 6) Gates + report.
    sync = av_sync(result["per_scene"], result["final_video"], result["final_audio"])
    print(f"final -> {result['path']}")
    print(f"final video={result['final_video']:.3f}s audio={result['final_audio']:.3f}s")
    print("per-scene A/V deltas:")
    for s in result["per_scene"]:
        print(f"  {s['id']}: video={s['video_dur']}s audio={s['audio_dur']}s delta={s['delta']}s")
    print("anchor alignment (target |delta| < 0.4s):")
    for a in anchor_report:
        print(f"  {a['id']}: '{a['word']}' word={a['time']}s anim_start={a['anim_start']}s delta={a['delta']}s")
    print(f"A/V SYNC OK = {sync['ok']} (max_scene_delta={sync['max_scene_delta']}s, final_delta={sync['final_delta']}s)")

    return {"engine": spoken["engine"], "result": result, "sync": sync, "anchors": anchor_report, "mode": mode}


if __name__ == "__main__":
    out = main()
    sys.exit(0 if out["sync"]["ok"] else 1)
