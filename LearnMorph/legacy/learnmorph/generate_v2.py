"""Phase 2 closed-loop generator: profile -> today_demo_v2.mp4.

WHY this module is the proof of "closed loop":
- It contains ZERO hand-rolled style values. Every color, font-timing, speaking
  rate, and inter-scene pause is read from the EXTRACTED Style Profile via
  learnmorph.conditioning. Grep this file (and the template + driver it emits)
  for hex palette literals or `-r 145` style magic numbers: there are none.
- The script's narration + visual_hint slots come from the script-writer output
  (which was itself conditioned on the profile's style_descriptors / exemplars /
  intent_sequence). So script, visuals, and voice all trace back to the profile.

Pipeline:
    profile.json --conditioning--> {visual, narrator, script params}
    script_v2.json (narration + equation slots)
      -> per-scene Manim drivers (style+timing slots filled from `visual`)
      -> render each at 480p15
      -> narrate each scene with `say -r <profile wpm>`, `[[slnc <profile ms>]]`
      -> concat scene MP4s, mux narration -> today_demo_v2.mp4

Run from project root:
    uv run python -m learnmorph.generate_v2
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from learnmorph.conditioning import condition


def _render_env() -> dict:
    """Return an environment with the TeX bin dir on PATH for manim's LaTeX.

    WHY: manim renders MathTex by shelling out to `latex` then `dvisvgm`. On
    this machine LaTeX is TinyTeX; only `latex` is symlinked into /usr/local/bin,
    so `dvisvgm` (which lives alongside it in the TinyTeX bin dir) is not on
    PATH and the second scene's fresh equations fail to convert. We resolve the
    real `latex` location and prepend its directory so the whole TeX toolchain
    is reachable. No-op if dvisvgm is already on PATH.
    """
    env = os.environ.copy()
    if shutil.which("dvisvgm"):
        return env
    latex = shutil.which("latex")
    if latex:
        tex_bin = str(Path(latex).resolve().parent)
        env["PATH"] = tex_bin + os.pathsep + env.get("PATH", "")
    return env


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "outputs" / "profiles" / "WUvTyaaNkzM.json"
SCRIPT = ROOT / "outputs" / "scripts" / "completing_square_v2.json"
SCENES_DIR = ROOT / "outputs" / "scenes"
AUDIO_DIR = ROOT / "outputs" / "audio" / "completing_square_v2"
FINAL = ROOT / "outputs" / "final" / "today_demo_v2.mp4"


# Shared block of profile-derived style + timing slots, emitted into every
# generated driver. Keeping it in one place means the closed-loop guarantee
# ("no hand-rolled style values") holds for every template a scene may use.
def _style_slots(visual: dict) -> str:
    return f'''    primary_color = "{visual["primary_color"]}"
    accent_color = "{visual["accent_color"]}"
    bg_color = "{visual["bg_color"]}"
    write_run_time = {visual["write_run_time"]}
    caption_run_time = {visual["caption_run_time"]}
    settle_wait = {visual["settle_wait"]}
    morph_run_time = {visual["morph_run_time"]}
    hold_wait = {visual["hold_wait"]}
    fade_run_time = {visual["fade_run_time"]}'''


_DRIVER_HEADER = '''"""Generated v2 driver — DO NOT hand-edit.

Content slots from outputs/scripts/completing_square_v2.json (script-writer,
conditioned on the profile). Style + timing slots from
outputs/profiles/WUvTyaaNkzM.json via learnmorph.conditioning. No hand-rolled
style values live here.
"""
'''


def _split_value(equation_from: str) -> str:
    """Half the linear coefficient b, read from the scene's source equation.

    The geometric area model needs b/2 (the rectangle width / corner side). We
    parse it from the script's `equation_from` (e.g. 'x^2 + 6x + 9' -> b=6 ->
    '3') so the geometry stays in sync with the algebra the script chose. Falls
    back to '3' (the demo default) if no integer coefficient is found.
    """
    m = re.search(r"([0-9]+)\s*x\b", equation_from)
    if m:
        b = int(m.group(1))
        half = b / 2
        return str(int(half)) if half.is_integer() else str(half)
    return "3"


def write_driver(idx: int, scene: dict, visual: dict) -> Path:
    """Emit a tiny driver. Content slots come from the script's visual_hint;
    EVERY style + timing slot comes from the profile-derived `visual` params.

    The TEMPLATE is chosen from the scene's pedagogy intent: a
    'build-intuition-geometrically' beat renders the geometric AreaModel
    (square + b/2 rectangles + completing corner), every other beat uses the
    EquationTransform morph. This is what makes the profile's
    `build-intuition-geometrically` intent visible, not merely narrated, and
    pulls in the profile's geometric motion_vocabulary.
    """
    vh = scene["visual_hint"]
    intent = scene.get("intent", "")
    cls = f"V2Scene{idx:02d}"

    if "geometr" in intent:
        body = (
            _DRIVER_HEADER
            + "\nfrom templates.area_model import AreaModel\n\n\n"
            + f"class {cls}(AreaModel):\n"
            + '    side_label = r"x"\n'
            + f'    split_value = r"{_split_value(vh["equation_from"])}"\n'
            + f'    caption_text = "{vh["caption"]}"\n'
            + _style_slots(visual)
            + "\n"
        )
    else:
        body = (
            _DRIVER_HEADER
            + "\nfrom templates.equation_transform import EquationTransform\n\n\n"
            + f"class {cls}(EquationTransform):\n"
            + f'    equation_a = r"{vh["equation_from"]}"\n'
            + f'    equation_b = r"{vh["equation_to"]}"\n'
            + f'    caption_text = "{vh["caption"]}"\n'
            + _style_slots(visual)
            + "\n"
        )

    path = SCENES_DIR / f"v2_scene_{idx:02d}.py"
    path.write_text(body)
    return path


def render(driver: Path, idx: int) -> Path:
    """Render one driver at 480p15 and copy the MP4 next to the drivers.

    WHY `python -m manim` with the current interpreter (not `uv run manim` and
    not the `manim` console script): we are already inside the project venv. A
    nested `uv run` re-bootstraps the env to a stale path, and the relocated
    venv's `manim` wrapper has a stale shebang. Running manim as a module with
    sys.executable is the deterministic, relocation-proof option.
    """
    cls = f"V2Scene{idx:02d}"
    rel = driver.relative_to(ROOT)
    subprocess.run(
        [sys.executable, "-m", "manim", "-ql", str(rel), cls],
        cwd=ROOT,
        check=True,
        env=_render_env(),
    )
    src = ROOT / "media" / "videos" / driver.stem / "480p15" / f"{cls}.mp4"
    dst = SCENES_DIR / f"v2_scene_{idx:02d}.mp4"
    dst.write_bytes(src.read_bytes())
    return dst


def narrate(script: dict, narrator: dict) -> Path:
    """Synthesize narration with macOS `say`, profile-driven rate + pauses.

    Rate comes from audio.pace_wpm (`say -r`); the inter-scene pause comes from
    audio.pause_pattern (`[[slnc N]]`). No voice cloning — we control prosody by
    speaking rate only, with the default system voice. Returns combined AIFF.
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    rate = narrator["say_rate_wpm"]
    pause_ms = narrator["pause_ms"]
    aiffs: list[Path] = []
    for scene in script["scenes"]:
        # Prepend a profile-length pause so the rhythm between beats matches the
        # source teacher's pacing (the `[[slnc]]` command is read by `say`).
        text = f"[[slnc {pause_ms}]] {scene['narration']}"
        out = AUDIO_DIR / f"{scene['id']}.aiff"
        subprocess.run(["say", "-r", str(rate), "-o", str(out), text], check=True)
        aiffs.append(out)

    concat = AUDIO_DIR / "concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in aiffs))
    combined = AUDIO_DIR / "combined.aiff"
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
            "-c",
            "copy",
            str(combined),
        ],
        check=True,
    )
    return combined


def stitch(scene_mp4s: list[Path], audio: Path) -> None:
    """Concat scene MP4s, then mux the narration track into the final MP4."""
    concat = SCENES_DIR / "v2_concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in scene_mp4s))
    silent = SCENES_DIR / "v2_silent.mp4"
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
            "-c",
            "copy",
            str(silent),
        ],
        check=True,
    )
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(FINAL),
        ],
        check=True,
    )


def main() -> None:
    params = condition(PROFILE)
    visual, narrator = params["visual"], params["narrator"]
    print(
        f"profile-driven look -> bg={visual['bg_color']} "
        f"primary={visual['primary_color']} accent={visual['accent_color']} "
        f"| say -r {narrator['say_rate_wpm']} pause={narrator['pause_ms']}ms"
    )
    script = json.loads(SCRIPT.read_text())

    mp4s = [render(write_driver(i, s, visual), i) for i, s in enumerate(script["scenes"], start=1)]
    audio = narrate(script, narrator)
    stitch(mp4s, audio)
    print(f"today_demo_v2 -> {FINAL}")


if __name__ == "__main__":
    main()
