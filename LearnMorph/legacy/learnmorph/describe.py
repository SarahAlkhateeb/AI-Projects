"""Stage — frames → text descriptions via Gemini.

WHY a vision model here:
- We have JPG frames (visual beats) but the profile fusion stage reasons over
  *text*. We need a faithful, structured description of what each frame shows:
  palette, on-screen objects, layout, motion cues. Gemini 2.5 Pro is strong at
  this and cheap enough for ~20 frames.

WHY ask for strict JSON per frame:
- The profile stage fuses these descriptions programmatically. Free-form prose
  is brittle to parse; a fixed JSON shape per frame keeps the pipeline
  deterministic downstream.

WHY GOOGLE_API_KEY from the environment:
- Locked project rule: API keys via os.environ after load_dotenv(); never
  hard-coded. This stage is the one that REQUIRES the key.
"""

import json
import os
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from google.api_core.exceptions import ResourceExhausted

# Preferred model (per brief) first, then a free-tier fallback.
# WHY the fallback: as of mid-2026 Google set the *free-tier* request limit for
# `gemini-2.5-pro` to 0 — a key without billing gets a hard 429 on every Pro
# call. `gemini-2.5-flash` is the documented free-tier multimodal model and is
# more than capable of per-frame visual description. We try Pro first so a paid
# key still uses it, and degrade to Flash only on a quota error.
_MODEL_PREFERENCE = ("gemini-2.5-pro", "gemini-2.5-flash")

_FRAME_PROMPT = (
    "You are analysing one frame from a 3Blue1Brown-style mathematics explainer "
    "video. Describe ONLY what is visible. Respond with STRICT JSON, no markdown "
    "fences, with exactly these keys:\n"
    "{\n"
    '  "summary": "one sentence describing the frame",\n'
    '  "palette": ["#hex", ...]   // 2-5 dominant colors as hex,\n'
    '  "on_screen": ["text or object", ...]  // equations, labels, shapes shown,\n'
    '  "layout": "where things sit (e.g. centered equation, left graph)",\n'
    '  "motion_cue": "any implied motion/animation, or \\"static\\""\n'
    "}"
)


def describe_frames(
    frame_paths: list[Path],
    output_path: Path = Path("outputs/descriptions/descriptions.json"),
    model_name: str | None = None,
) -> dict:
    """Describe each frame as structured JSON using Gemini.

    Parameters
    ----------
    frame_paths : list[Path]
        Frames to describe, in time order (from frames.sample_frames).
    output_path : Path
        Where to write the combined descriptions JSON.
    model_name : str | None
        Gemini model id. If None (default), try gemini-2.5-pro first (per the
        brief) and fall back to gemini-2.5-flash on a free-tier quota (429).
        Pass an explicit id to pin one model.

    Returns
    -------
    dict with keys:
        path         -> Path to the saved descriptions JSON
        descriptions -> list of per-frame dicts (frame + parsed description)
        count        -> number of frames described (int)
    """
    load_dotenv()
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is missing or blank. Add it to .env "
            "(https://aistudio.google.com/apikey)."
        )
    genai.configure(api_key=api_key)

    # Build the model try-order: an explicit pin, else the preference list.
    candidates = [model_name] if model_name else list(_MODEL_PREFERENCE)
    active = candidates[0]
    model = genai.GenerativeModel(active)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate(image_part: dict):
        """Call the active model, handling free-tier 429s two ways:

        - A *per-day / limit-0* quota (e.g. Pro on a billing-free key) means
          the model is unusable: drop to the next candidate model and retry.
        - A *per-minute* rate cap on a model that otherwise works: back off and
          retry the SAME model a few times.

        WHY pick the fallback model once and keep it: after the first Pro 429
        we know Pro is quota-0, so every later frame should go straight to the
        fallback, never re-hitting Pro."""
        nonlocal active, model, candidates
        backoffs = 0
        while True:
            try:
                return model.generate_content([_FRAME_PROMPT, image_part])
            except ResourceExhausted:
                remaining = candidates[candidates.index(active) + 1 :]
                if remaining:
                    # A better-than-give-up option exists: switch models.
                    active = remaining[0]
                    model = genai.GenerativeModel(active)
                    continue
                # No fallback model left -> assume per-minute rate cap; back off.
                if backoffs >= 4:
                    raise
                backoffs += 1
                time.sleep(20)

    descriptions: list[dict] = []
    for fp in frame_paths:
        fp = Path(fp)
        image_part = {"mime_type": "image/jpeg", "data": fp.read_bytes()}
        try:
            resp = _generate(image_part)
        except ResourceExhausted:
            # The DAILY quota is gone (e.g. free-tier flash = 20 req/day). Don't
            # throw away the frames we DID describe — a partial profile from
            # several frames is far better than a crash. Stop the loop here and
            # write what we have, as long as it's non-empty.
            if not descriptions:
                raise
            break
        raw = (resp.text or "").strip()
        # Gentle pacing so a batch stays under free-tier per-minute limits.
        time.sleep(4)
        # Strip accidental markdown fences if the model adds them.
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Keep the pipeline alive: store the raw text so fusion can still
            # see *something* rather than crashing on one bad frame.
            parsed = {"summary": raw[:500], "_parse_error": True}
        descriptions.append({"frame": fp.name, "description": parsed})
        # Incremental save: persist after every frame so a later quota error
        # still leaves a usable descriptions.json on disk.
        output_path.write_text(json.dumps(descriptions, indent=2))

    output_path.write_text(json.dumps(descriptions, indent=2))

    return {
        "path": output_path,
        "descriptions": descriptions,
        "count": len(descriptions),
        "model_used": active,
    }


if __name__ == "__main__":
    import sys

    frame_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/frames/WUvTyaaNkzM")
    frames = sorted(frame_dir.glob("*.jpg"))
    result = describe_frames(frames)
    print(
        f"descriptions -> {result['path']} ({result['count']} frames, model={result['model_used']})"
    )
