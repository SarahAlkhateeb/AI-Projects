"""Stage — turn an extracted Style Profile into per-stage generation params.

WHY this module exists (it is the literal "close the loop" of Phase 2):
- Phase 1 hand-rolled the look: colors baked into drivers, voice/pace baked into
  the narrate call, pedagogy baked into the script prompt. That is style
  *imitation by a human*, not style *transfer by the system*.
- `conditioning.py` is the single seam where the EXTRACTED profile becomes the
  knobs every generation stage actually reads. Nothing downstream should hold a
  hand-picked style literal; it should ask this module instead.

The three consumers and what each needs:
- script-writer  <- style_descriptors (register adjectives), exemplars
                    (few-shot verbatim snippets), intent_sequence (ordered,
                    named teaching beats -> one scoped sub-instruction each).
- template driver <- visual.palette (bg/primary/accent), motion_vocabulary,
                    and timing derived from the audio pace.
- narrator        <- audio.pace_wpm -> macOS `say -r`; audio.pause_pattern ->
                    `[[slnc N]]` inter-scene pause in ms. (No voice cloning:
                    we control prosody by descriptor + rate only.)

Design notes:
- Every getter is defensive about the model-authored profile shape (missing
  keys, odd casing) but does NOT invent a 3b1b palette. If the profile lacks a
  value we surface a conservative neutral default and let it show — a wrong-
  looking frame is the honest signal that extraction missed something, far
  better than silently re-injecting the hand-rolled look we are trying to kill.
- Functions return dicts with named keys (project convention), never tuples.
"""

import json
import re
from pathlib import Path

# Neutral sentinels — intentionally NOT the 3b1b palette. See module docstring.
_DEFAULT_BG = "#202020"
_DEFAULT_PRIMARY = "#808080"
_DEFAULT_ACCENT = "#FFFFFF"
_DEFAULT_WPM = 150

# Cap the narration speaking rate at the point of CONSUMPTION, not in the
# profile. WHY: the source 3b1b clip was measured at ~173 wpm, but read back by
# a TTS engine that is fast crammed dense math into too-short scenes and sounded
# rushed/robotic. 3b1b's *teaching* delivery sits nearer ~140 wpm with audible
# pauses. We keep the raw extracted pace_wpm in the profile (it is a true
# measurement of the source) and only clamp the value the narrator actually
# speaks at. The profile stays honest; the output stays calm.
_NARRATION_WPM_CAP = 140


def load_profile(profile_path: Path) -> dict:
    """Read a Style Profile JSON from disk into a dict."""
    return json.loads(Path(profile_path).read_text())


def _hex(value: object, fallback: str) -> str:
    """Coerce a model-authored color to #RRGGBB, else fall back.

    WHY defensive: the palette comes from an LLM reading frame descriptions, so
    it may arrive without a leading '#', lower/upper-cased, or absent entirely.
    """
    if not isinstance(value, str) or not value.strip():
        return fallback
    v = value.strip()
    if not v.startswith("#"):
        v = "#" + v
    return v if len(v) in (4, 7) else fallback


def _pause_ms(pause_pattern: object, default_ms: int = 350) -> int:
    """Extract a representative inter-beat pause length in milliseconds.

    The profile's pause_pattern is a phrase like
    'brief ~400ms pause after each key claim; ~700ms at transitions'. We pull
    the FIRST millisecond figure as the per-claim pause the narrator inserts
    between scenes via macOS `say`'s `[[slnc N]]` command. WHY first, not max:
    the short per-claim pause is the rhythm that reads as "this teacher", the
    long transition pause is comparatively rare.
    """
    if isinstance(pause_pattern, str):
        ms = re.search(r"(\d{2,4})\s*ms", pause_pattern)
        if ms:
            return int(ms.group(1))
        # Some profiles phrase it in seconds ("a ~0.4s beat").
        sec = re.search(r"(\d+(?:\.\d+)?)\s*s(?:ec)?", pause_pattern)
        if sec:
            return round(float(sec.group(1)) * 1000)
    return default_ms


def visual_params(profile: dict) -> dict:
    """Style/timing knobs for a template driver, derived from the profile.

    Returns
    -------
    dict with keys consumed directly as EquationTransform class attributes:
        bg_color, primary_color, accent_color,
        write_run_time, caption_run_time, settle_wait,
        morph_run_time, hold_wait, fade_run_time
    """
    palette = (profile.get("visual") or {}).get("palette") or {}
    bg = _hex(palette.get("background"), _DEFAULT_BG)
    primary = _hex(palette.get("primary"), _DEFAULT_PRIMARY)
    accent = _hex(palette.get("accent") or palette.get("primary"), _DEFAULT_ACCENT)

    # Derive timing from speaking pace: a faster talker -> snappier beats. We
    # scale around the canonical ~150 wpm baseline and clamp so the animation
    # never becomes either frantic or sluggish. This keeps visual rhythm tied
    # to the EXTRACTED audio signal rather than to a hardcoded run_time.
    wpm = (profile.get("audio") or {}).get("pace_wpm") or _DEFAULT_WPM
    scale = max(0.6, min(1.6, _DEFAULT_WPM / float(wpm)))

    return {
        "bg_color": bg,
        "primary_color": primary,
        "accent_color": accent,
        "write_run_time": round(1.5 * scale, 2),
        "caption_run_time": round(1.0 * scale, 2),
        "settle_wait": round(0.5 * scale, 2),
        "morph_run_time": round(2.0 * scale, 2),
        "hold_wait": round(1.0 * scale, 2),
        "fade_run_time": round(0.8 * scale, 2),
        "motion_vocabulary": (profile.get("visual") or {}).get("motion_vocabulary") or [],
    }


def narrator_params(profile: dict) -> dict:
    """Prosody knobs for the narrator, derived from the profile.

    Returns
    -------
    dict with keys:
        say_rate_wpm -> int, passed to macOS `say -r`
        pause_ms     -> int, inter-scene `[[slnc N]]` pause length
        voice_descriptor -> str, for logging / future engines (NOT cloning)
    """
    audio = profile.get("audio") or {}
    raw_wpm = int(audio.get("pace_wpm") or _DEFAULT_WPM)
    # Clamp at consumption: never narrate faster than the calm cap, and keep it
    # in the intelligible `say -r` range (~90-300). The profile keeps raw_wpm.
    spoken_wpm = max(90, min(_NARRATION_WPM_CAP, raw_wpm))
    return {
        "profile_wpm": raw_wpm,
        "say_rate_wpm": spoken_wpm,
        # ElevenLabs voice_settings.speed is a 0.7-1.2 multiplier around 1.0 (1.0
        # ~= the model's natural pace). Map the clamped target rate to that band
        # relative to a ~150 wpm natural baseline, then clamp to the valid range.
        "el_speed": round(max(0.7, min(1.2, spoken_wpm / float(_DEFAULT_WPM))), 2),
        "pause_ms": _pause_ms(audio.get("pause_pattern")),
        "voice_descriptor": str(audio.get("voice_descriptor") or "calm conversational"),
    }


def script_params(profile: dict) -> dict:
    """Conditioning material for the script-writer, derived from the profile.

    Returns
    -------
    dict with keys:
        style_descriptors -> list[str], used as "write to be more [descriptors]"
        intent_sequence   -> list[str], one ordered scene per named intent
        exemplars         -> list[dict], verbatim few-shot demonstrations
        style_instruction -> str, a ready-to-inject system fragment combining
                             the above into a concrete brief
    """
    descriptors = profile.get("style_descriptors") or []
    pedagogy = profile.get("pedagogy") or {}
    intents = pedagogy.get("intent_sequence") or []
    exemplars = profile.get("exemplars") or []

    # Build a few-shot block from VERBATIM snippets — concrete demonstrations are
    # the load-bearing signal (adjectives alone are weak, per the brief).
    shots = []
    for ex in exemplars:
        snippet = (ex.get("transcript_snippet") or "").strip()
        if snippet:
            techniques = ", ".join(ex.get("illustrates") or [])
            shots.append(
                f'- "{snippet}"' + (f"  (illustrates: {techniques})" if techniques else "")
            )

    instruction_parts: list[str] = []
    if descriptors:
        instruction_parts.append("Write the narration to be more " + ", ".join(descriptors) + ".")
    if shots:
        instruction_parts.append(
            "Match the VOICE of these verbatim lines from the source teacher "
            "(echo their rhythm and register, do not copy their words):\n" + "\n".join(shots)
        )
    if intents:
        numbered = "\n".join(f"  {i + 1}. {name}" for i, name in enumerate(intents))
        instruction_parts.append(
            "Structure the lesson as an ORDERED checklist of teaching intents, "
            "one scene per intent, in this exact order:\n" + numbered
        )

    return {
        "style_descriptors": descriptors,
        "intent_sequence": intents,
        "exemplars": exemplars,
        "style_instruction": "\n\n".join(instruction_parts),
    }


def condition(profile_path: Path) -> dict:
    """One call -> all per-stage params. The single entrypoint downstream uses.

    Returns
    -------
    dict with keys: profile, visual, narrator, script
    """
    profile = load_profile(profile_path)
    return {
        "profile": profile,
        "visual": visual_params(profile),
        "narrator": narrator_params(profile),
        "script": script_params(profile),
    }


if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/profiles/WUvTyaaNkzM.json")
    out = condition(path)
    print("VISUAL  ", json.dumps(out["visual"], indent=2))
    print("NARRATOR", json.dumps(out["narrator"], indent=2))
    print("SCRIPT INSTRUCTION:\n", out["script"]["style_instruction"])
