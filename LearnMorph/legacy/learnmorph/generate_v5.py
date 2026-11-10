"""Phase-3 P1-P3: narration-first micro-beats -> today_demo_v5.mp4 (~60s).

WHY beats (review complaint 2, root-caused): v4 rendered 13.98s of animation
for an 8.08s narration and the assembler CHOPPED 42% of the geometric
explanation mid-motion. The deeper bug: scene-sized animation and scene-sized
narration were timed independently and reconciled at the end. Beats invert
that: ONE sentence = ONE beat = ONE visual event. Each beat's narration is
synthesized FIRST; its measured duration is passed INTO the template as
target_duration; the template fits itself (rest on the final frame if short,
uniform compress if long). The assembler then only ever pads a frame-hold tail.
A HARD GUARD fails the build if any beat would lose > 0.25s of rendered
animation — this class of bug can no longer ship silently (also wired into
verify_dod).

WHY the storyboard lives HERE as data (not an LLM call): the v5 lesson's math
(equation part-splits, highlight indices, geometry stages) must be exactly
right; the LLM writes only the per-beat NARRATION. Phase-3 P4 will grow the
LLM-routed storyboard for arbitrary topics; for the flagship lesson the mapping
is pinned.

WHY no imports of generated driver files: v4's post_anchor_scale silently
rendered at 1.0 because a probe-import wrote __pycache__ for a driver that was
rewritten with SAME byte length in the SAME mtime second — manim then trusted
the stale bytecode. Here timing probes run against the TEMPLATE classes with
slot values applied in memory, and each driver file is written exactly once.

Engine policy: ElevenLabs ONLY (user-authorized), fail loud, never a silent
`say` fallback. Existing per-beat MP3s are reused so re-runs spend nothing.

Run from project root:
    uv run python -m learnmorph.generate_v5
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from learnmorph.assemble import assemble
from learnmorph.conditioning import condition
from learnmorph.eval_metrics import av_sync
from learnmorph.generate_v2 import _render_env, _style_slots
from learnmorph.narrate import elevenlabs_available, narrate

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "outputs" / "profiles" / "WUvTyaaNkzM.json"
SCRIPT = ROOT / "outputs" / "scripts" / "completing_square_v5.json"
SCENES_DIR = ROOT / "outputs" / "scenes"
FINAL = ROOT / "outputs" / "final" / "today_demo_v5.mp4"

_TRIM_TOLERANCE = 0.25  # max seconds of rendered animation the mux may cut
_RENDER_CAP_SECONDS = 300
_MODES = {
    "1080p60": {"flags": ["-qh"], "subdir": "1080p60", "fps": 60},
    "1080p30": {"flags": ["--resolution", "1920,1080", "--fps", "30"], "subdir": "1080p30", "fps": 30},
}

# --- The v5 lesson storyboard: 8 beats, one visual event each ---------------
# template: "step" = EquationStepThrough, "area" = AreaModel (staged).
STORYBOARD: list[dict] = [
    {"id": "b01", "template": "step",
     "params": {"parts_a": ("x^2", "+6x", "+5"), "parts_b": (),
                "highlight_a": (), "highlight_b": (),
                "caption_text": "Can this become a square?"}},
    {"id": "b02", "template": "area",
     "params": {"stage": "square", "caption_text": "x squared, literally"}},
    {"id": "b03", "template": "area",
     "params": {"stage": "strips", "caption_text": "6x = two strips of 3"}},
    {"id": "b04", "template": "area",
     "params": {"stage": "corner", "caption_text": "The gap is 3 by 3 = 9"}},
    {"id": "b05", "template": "step",
     "params": {"parts_a": ("x^2", "+6x", "+5"),
                "parts_b": ("x^2", "+6x", "+9", "-9", "+5"),
                "highlight_a": (), "highlight_b": (2, 3),
                "caption_text": "Add 9, take 9 back"}},
    {"id": "b06", "template": "step",
     "params": {"parts_a": ("x^2", "+6x", "+9", "-9", "+5"),
                "parts_b": ("(x+3)^2", "-9", "+5"),
                "highlight_a": (), "highlight_b": (0,),
                "caption_text": "Three terms fold into one square"}},
    {"id": "b07", "template": "step",
     "params": {"parts_a": ("(x+3)^2", "-9", "+5"),
                "parts_b": ("(x+3)^2", "-4"),
                "highlight_a": (), "highlight_b": (1,),
                "caption_text": "Tidy up the leftovers"}},
    {"id": "b08", "template": "step",
     "params": {"parts_a": ("x^2", "+bx"),
                "parts_b": ("(x+", "b/2", ")^2", "-(", "b/2", ")^2"),
                "highlight_a": (), "highlight_b": (1, 4),
                "caption_text": "The recipe, for any quadratic"}},
]

_AREA_EXTRA = {"side_label": "x", "split_value": "3"}  # b=6 -> split 3

_DRIVER_HEADER = '''"""Generated v5 beat driver — DO NOT hand-edit.

Storyboard params from learnmorph/generate_v5.py; style + timing from the
extracted profile via conditioning; target_duration = this beat's narration
length (narration-first micro-beats).
"""
'''


def _fmt(value) -> str:
    """Format a slot value for the generated driver source."""
    if isinstance(value, tuple):
        inner = ", ".join(f'r"{v}"' if isinstance(v, str) else repr(v) for v in value)
        return f"({inner},)" if value else "()"
    if isinstance(value, str):
        return f'r"{value}"'
    return repr(value)


def _probe(template: str, params: dict, visual: dict, target: float):
    """In-memory timing probe: template class + slot values, NO generated-file
    import (see module docstring for the __pycache__ trap this avoids)."""
    if template == "step":
        from templates.equation_step_through import EquationStepThrough as cls
    else:
        from templates.area_model import AreaModel as cls
    probe = object.__new__(cls)
    for key, val in {**params, **visual, "target_duration": target}.items():
        if key != "motion_vocabulary":
            setattr(probe, key, val)
    return probe


def write_driver(idx: int, beat: dict, visual: dict, target: float) -> Path:
    """Write one beat driver, exactly once."""
    cls = f"V5Beat{idx:02d}"
    params = dict(beat["params"])
    if beat["template"] == "step":
        imp = "from templates.equation_step_through import EquationStepThrough"
        base = "EquationStepThrough"
    else:
        imp = "from templates.area_model import AreaModel"
        base = "AreaModel"
        params = {**_AREA_EXTRA, **params}

    lines = [f"    {k} = {_fmt(v)}" for k, v in params.items()]
    lines.append(f"    target_duration = {target:.3f}")
    body = (
        _DRIVER_HEADER
        + f"\n{imp}\n\n\nclass {cls}({base}):\n"
        + "\n".join(lines)
        + "\n"
        + _style_slots(visual)
        + "\n"
    )
    path = SCENES_DIR / f"v5_beat_{idx:02d}.py"
    path.write_text(body)
    return path


def render(driver: Path, idx: int, mode: str) -> tuple[Path, float]:
    cls = f"V5Beat{idx:02d}"
    cfg = _MODES[mode]
    rel = driver.relative_to(ROOT)
    t0 = time.monotonic()
    subprocess.run(
        [sys.executable, "-m", "manim", *cfg["flags"], str(rel), cls],
        cwd=ROOT, check=True, env=_render_env(),
    )
    elapsed = time.monotonic() - t0
    src = ROOT / "media" / "videos" / driver.stem / cfg["subdir"] / f"{cls}.mp4"
    dst = SCENES_DIR / f"v5_raw_{idx:02d}.mp4"  # never collides with mux names
    dst.write_bytes(src.read_bytes())
    return dst, elapsed


def _dur(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def main() -> dict:
    if not elevenlabs_available():
        print("FATAL: ElevenLabs unavailable (key or SDK missing). No `say` fallback for finals.")
        sys.exit(2)

    visual = condition(PROFILE)["visual"]
    script = json.loads(SCRIPT.read_text())
    beats = script["beats"]
    if [b["id"] for b in beats] != [s["id"] for s in STORYBOARD]:
        print("FATAL: script beats do not match the storyboard ids.")
        sys.exit(2)

    # 1) Narrate each beat (reuse cached MP3s — re-runs spend zero characters).
    audio_dir = ROOT / "outputs" / "audio" / "completing_square_v5"
    cached = [audio_dir / f"{b['id']}.mp3" for b in beats]
    if all(p.exists() for p in cached):
        spoken_scenes = [
            {"id": b["id"], "path": p, "duration": round(_dur(p), 3)}
            for b, p in zip(beats, cached, strict=True)
        ]
        print("narration: REUSING existing ElevenLabs clips (no characters spent)")
    else:
        # narrate() reads script["scenes"]; adapt the beat script shape.
        shim = {"scenes": beats}
        shim_path = audio_dir.parent / "_v5_shim.json"
        shim_path.parent.mkdir(parents=True, exist_ok=True)
        shim_path.write_text(json.dumps(shim))
        try:
            spoken = narrate(shim_path, PROFILE, slug="completing_square_v5")
        except Exception as exc:
            print(f"FATAL: ElevenLabs narration failed: {exc!r}")
            sys.exit(2)
        if spoken["engine"] != "elevenlabs":
            print(f"FATAL: expected engine=elevenlabs, got {spoken['engine']}.")
            sys.exit(2)
        spoken_scenes = spoken["scenes"]
    total_audio = round(sum(s["duration"] for s in spoken_scenes), 3)
    print(f"narration engine = elevenlabs (total {total_audio}s across {len(beats)} beats)")

    # 2) Per beat: driver (written once) -> render -> NO-TRIM guard.
    mode = "1080p60"
    raw_videos: list[Path] = []
    beat_rows: list[dict] = []
    trims: list[str] = []
    for i, (story, aud) in enumerate(zip(STORYBOARD, spoken_scenes, strict=True), start=1):
        target = float(aud["duration"])
        probe = _probe(story["template"], story["params"], visual, target)
        predicted = probe.fitted_duration()

        driver = write_driver(i, story, visual, target)
        mp4, secs = render(driver, i, mode)
        raw = _dur(mp4)
        trim = max(0.0, raw - target)
        beat_rows.append(
            {"id": story["id"], "template": story["template"], "audio": round(target, 3),
             "raw_render_seconds": round(raw, 3), "predicted": round(predicted, 3),
             "trim_seconds": round(trim, 3)}
        )
        print(f"  {story['id']} [{story['template']}] audio={target:.2f}s "
              f"render={raw:.2f}s trim={trim:.2f}s ({mode}, {secs:.0f}s wall)")
        if trim > _TRIM_TOLERANCE:
            trims.append(f"{story['id']}: render {raw:.2f}s > audio {target:.2f}s "
                         f"by {trim:.2f}s (> {_TRIM_TOLERANCE}s)")
        if secs > _RENDER_CAP_SECONDS and mode == "1080p60":
            mode = "1080p30"
            print(f"  render exceeded {_RENDER_CAP_SECONDS}s -> remaining beats at 1080p30")
        raw_videos.append(mp4)

    if trims:
        print("FATAL: NO-TRIM guard tripped — animation would be cut mid-motion:")
        for t in trims:
            print(f"  {t}")
        sys.exit(3)

    # 3) Assemble (per-beat fit+mux, then concat) at the render frame rate.
    result = assemble(raw_videos, spoken_scenes, FINAL, prefix="v5", fps=_MODES[mode]["fps"])

    # 4) Manifest (verify_dod reads this: intended narration AND no-trim data).
    manifest = {
        "engine": "elevenlabs",
        "final_video": str(FINAL),
        "render_mode": mode,
        "scenes": [
            {"id": s["id"], "audio": str(s["path"]), "duration": s["duration"]}
            for s in spoken_scenes
        ],
        "intended_narration_seconds": total_audio,
        "beats": beat_rows,
        "trim_tolerance_seconds": _TRIM_TOLERANCE,
    }
    FINAL.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))

    # 5) Gates + report.
    sync = av_sync(result["per_scene"], result["final_video"], result["final_audio"])
    print(f"final -> {result['path']}")
    print(f"final video={result['final_video']:.3f}s audio={result['final_audio']:.3f}s")
    print("per-beat A/V deltas:")
    for s in result["per_scene"]:
        print(f"  {s['id']}: video={s['video_dur']}s audio={s['audio_dur']}s delta={s['delta']}s")
    print(f"A/V SYNC OK = {sync['ok']} (max_beat_delta={sync['max_scene_delta']}s, "
          f"final_delta={sync['final_delta']}s) | trims: none > {_TRIM_TOLERANCE}s")
    return {"result": result, "sync": sync, "beats": beat_rows, "mode": mode}


if __name__ == "__main__":
    out = main()
    sys.exit(0 if out["sync"]["ok"] else 1)
