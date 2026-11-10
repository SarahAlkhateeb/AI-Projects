"""Stage — script JSON -> per-scene narration audio (engine-agnostic).

WHY engine-agnostic with a clean fallback:
- The pipeline must run with ZERO setup (free macOS `say`), but produce premium
  audio when an ElevenLabs key is present. So the public function `narrate()`
  picks the engine by capability: ElevenLabs IF `ELEVENLABS_API_KEY` is set AND
  the SDK imports, else macOS `say`. The caller does not branch.

WHY PER-SCENE files (not one combined track):
- The Phase-2 desync bug came from muxing ONE combined audio track over a
  concatenated video whose per-scene lengths did not match. The fix lives in the
  assembler, but it depends on this stage returning each scene's audio + its
  measured duration so the assembler can time each video clip to its own line.

WHY pacing/pauses come from the PROFILE (conditioning), never hardcoded:
- Closed-loop rule: the speaking rate (`say -r` / ElevenLabs `voice_settings.
  speed`) and the inter-claim pause length both trace back to the extracted
  profile via learnmorph.conditioning.narrator_params(). We CLAMP the rate to a
  calm cap at consumption (see conditioning), the profile keeps the raw value.

NEVER voice cloning (locked rule 4):
- The ElevenLabs branch uses a PREBUILT library voice id only and exposes prosody
  via voice_settings + v3 audio tags. It never uploads source audio, never
  creates or uses a cloned voice. Source-creator voices are never imitated.

ElevenLabs API specifics are verified against the 2026 official docs:
- SDK: `from elevenlabs.client import ElevenLabs`; `ElevenLabs(api_key=...)`.
- TTS: `client.text_to_speech.convert(text=, voice_id=, model_id=,
  output_format=, voice_settings=)` -> iterable of audio byte chunks.
- model `eleven_v3` (GA) supports bracketed audio tags ([pause], [speed x.x]);
  SSML <break> is NOT supported by v3, so pauses use audio tags.
- voice_settings.speed is 0.7-1.2 (lower = calmer); stability/style tune tone.
"""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from learnmorph.conditioning import condition

# Prebuilt DEFAULT voice "George" (calm, warm) — NOT a clone, and does not
# imitate any source creator. WHY this specific id: on the free/scoped key the
# old "library" voices (e.g. Rachel 21m00Tcm4TlvDq8ikWAM) return HTTP 402, while
# the default voices (George/Brian/Sarah/Bill/Daniel) return 200 with real audio.
# The key is also scoped to text_to_speech only (no voices_read/user_read), so we
# HARDCODE the voice id and never call /v1/voices or /v1/user (they would 401).
_EL_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George — default, free-usable, no cloning
_EL_MODEL = "eleven_v3"  # GA; supports audio tags for calm pacing/pauses
_EL_OUTPUT_FORMAT = "mp3_44100_128"


# Smart-punctuation -> ASCII map. Keys use \u escapes so the source file stays
# ASCII-clean (no ambiguous-character lint, no encoding surprises). These cover
# the smart dashes/quotes/ellipsis a script-writer model may emit.
_SMART_PUNCT = {
    "\u2014": ", ",  # em dash
    "\u2013": ", ",  # en dash
    "\u2019": "'",  # right single quote
    "\u2018": "'",  # left single quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2026": "...",  # ellipsis
}


def _ascii(text: str) -> str:
    """Down-convert smart punctuation to ASCII so any engine reads it cleanly."""
    for src, dst in _SMART_PUNCT.items():
        text = text.replace(src, dst)
    return text


def _duration(path: Path) -> float:
    """Audio/video duration in seconds via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def elevenlabs_available() -> bool:
    """True iff the ElevenLabs branch can run: key present AND SDK importable.

    WHY both checks: the key alone is useless without the SDK, and the SDK alone
    cannot authenticate without the key. Either missing -> fall back to `say`.
    """
    load_dotenv()
    if not os.environ.get("ELEVENLABS_API_KEY", "").strip():
        return False
    try:
        import elevenlabs.client  # noqa: F401
    except Exception:
        return False
    return True


def _say_scene(text: str, out_path: Path, rate_wpm: int, pause_ms: int) -> Path:
    """Synthesize one scene with macOS `say`. Pause uses `[[slnc N]]`."""
    spoken = f"[[slnc {pause_ms}]] {_ascii(text)}"
    subprocess.run(["say", "-r", str(rate_wpm), "-o", str(out_path), spoken], check=True)
    return out_path


# Tone tags a script may request per scene (eleven_v3 audio-tag vocabulary).
# WHY a whitelist: tags are free text to the API, so we constrain them to the
# documented emotion/delivery set to avoid the model reading junk aloud.
_ALLOWED_TONE_TAGS = {"[calm]", "[curious]", "[warm]", "[excited]", "[whisper]"}


def _el_scene(
    text: str,
    out_path: Path,
    speed: float,
    pause_ms: int,
    tone_tag: str = "[calm]",
) -> Path:
    """Synthesize one scene with ElevenLabs (prebuilt voice; no cloning).

    Pauses are expressed with a v3 audio tag (SSML <break> is unsupported by v3);
    longer profile pauses -> [long pause], else [short pause]. The TONE tag is
    contextual per scene (the script chooses it to match the beat's intent —
    curious for the puzzle, warm for the intuition — instead of a mechanical
    [calm] on every line). voice_settings tuned for a warmer, more human read:
    stability 0.5 ("natural" band) and style 0.35 give expressive variation
    without wobble; speed stays profile-driven (clamped calm).
    """
    from elevenlabs.client import ElevenLabs

    if tone_tag not in _ALLOWED_TONE_TAGS:
        tone_tag = "[calm]"
    pause_tag = "[long pause]" if pause_ms >= 600 else "[short pause]"
    prompt = f"{tone_tag} {pause_tag} {_ascii(text)}"

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"].strip())
    audio = client.text_to_speech.convert(
        text=prompt,
        voice_id=_EL_VOICE_ID,
        model_id=_EL_MODEL,
        output_format=_EL_OUTPUT_FORMAT,
        voice_settings={
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.35,
            "speed": speed,  # 0.7-1.2; clamped-calm value from conditioning
            "use_speaker_boost": False,
        },
    )
    with open(out_path, "wb") as fh:
        for chunk in audio:
            if chunk:
                fh.write(chunk)
    return out_path


def narrate(script_path: Path, profile_path: Path, slug: str | None = None) -> dict:
    """Synthesize per-scene narration for a script, conditioned on a profile.

    Engine is chosen automatically: ElevenLabs if available, else macOS `say`.
    Pace + pause are profile-driven (clamped calm) via conditioning.

    Returns
    -------
    dict with keys:
        engine        -> "elevenlabs" | "say"
        slug          -> output subdir name under outputs/audio/
        scenes        -> list of {"id", "path", "duration"} per scene, in order
        total_seconds -> sum of per-scene durations
    """
    script_path, profile_path = Path(script_path), Path(profile_path)
    import json

    script = json.loads(script_path.read_text())
    slug = slug or script_path.stem

    narrator = condition(profile_path)["narrator"]
    out_dir = Path("outputs/audio") / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    use_el = elevenlabs_available()
    engine = "elevenlabs" if use_el else "say"
    ext = "mp3" if use_el else "aiff"

    scenes: list[dict] = []
    for scene in script["scenes"]:
        text = (scene.get("narration") or "").strip()
        if not text:
            continue
        out = out_dir / f"{scene['id']}.{ext}"
        if use_el:
            _el_scene(
                text,
                out,
                narrator["el_speed"],
                narrator["pause_ms"],
                tone_tag=scene.get("tone_tag", "[calm]"),
            )
        else:
            _say_scene(text, out, narrator["say_rate_wpm"], narrator["pause_ms"])
        scenes.append({"id": scene["id"], "path": out, "duration": _duration(out)})

    return {
        "engine": engine,
        "slug": slug,
        "scenes": scenes,
        "total_seconds": round(sum(s["duration"] for s in scenes), 3),
    }


if __name__ == "__main__":
    import sys

    sp = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("outputs/scripts/completing_square_v3.json")
    )
    pp = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("outputs/profiles/WUvTyaaNkzM.json")
    result = narrate(sp, pp)
    print(f"engine={result['engine']} total={result['total_seconds']}s")
    for s in result["scenes"]:
        print(f"  {s['id']}: {s['duration']:.2f}s -> {s['path']}")
