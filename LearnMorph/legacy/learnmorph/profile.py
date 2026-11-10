"""Stage — fuse transcript + frame descriptions into a Style Profile JSON.

WHY a single fusion step:
- transcribe.py gives us the *audio* signal (words + timings), describe.py gives
  us the *visual* signal (per-frame structured descriptions). The Style Profile
  is the join of those two modalities plus a pedagogy read. One LLM call that
  sees BOTH is the cleanest way to produce a coherent profile.

WHY claude-sonnet-4-6:
- Strong structured-output model, current Sonnet. The brief pins it explicitly
  (ROADMAP still says "4.5" — 4.6 supersedes it). We force JSON via a strict
  prompt and parse the result; no free-form prose leaks downstream.

WHY this module is the end-to-end entrypoint:
- `python -m learnmorph.profile <video_url>` runs the WHOLE extraction pipeline:
  download -> transcribe -> frames -> describe -> fuse -> write profile JSON.
  That single command is the Phase 2 Definition-of-done check.
"""

import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from learnmorph.describe import describe_frames
from learnmorph.download import download_video
from learnmorph.frames import sample_frames
from learnmorph.transcribe import transcribe_audio

_FUSION_MODEL = "claude-sonnet-4-6"

_SCHEMA_HINT = """{
  "audio":    { "pace_wpm": <int>, "voice_descriptor": "<short phrase>",
                "pause_pattern": "<short phrase, mention rough pause length in ms if you can>" },
  "visual":   { "palette": { "background": "#hex", "primary": "#hex", "accent": "#hex" },
                "motion_vocabulary": ["<verb-ish phrase>", ...],
                "layout_patterns": ["<phrase>", ...] },
  "pedagogy": { "complexity_curve": "<phrase>",
                "scaffolding_moves": ["<phrase>", ...],
                "intent_sequence": ["<named-intent>", "<named-intent>", "<named-intent>"] },
  "style_descriptors": ["<adjective>", "<adjective>", "<adjective>"],
  "exemplars": [ { "transcript_snippet": "<VERBATIM quote from the transcript>",
                   "frame": "<frame filename, e.g. scene_03.jpg>",
                   "illustrates": ["<technique>", ...] } ]
}"""


def _measure_pace_wpm(words: list[dict], duration: float) -> int:
    """Words-per-minute from word timings. WHY: grounds pace_wpm in real data
    instead of letting the LLM guess it."""
    if duration <= 0 or not words:
        return 0
    return round(len(words) / (duration / 60.0))


def fuse_profile(
    transcript: dict,
    descriptions: list[dict],
    video_id: str,
    output_dir: Path = Path("outputs/profiles"),
) -> dict:
    """Fuse transcript + frame descriptions into a Style Profile JSON file.

    Parameters
    ----------
    transcript : dict
        Result of transcribe_audio (needs "text", "words", "duration").
    descriptions : list[dict]
        Result list from describe_frames (per-frame description dicts).
    video_id : str
        YouTube id — used as the profile filename.
    output_dir : Path
        Where to write outputs/profiles/{video_id}.json.

    Returns
    -------
    dict with keys:
        path    -> Path to the saved profile JSON
        profile -> the parsed profile dict
    """
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing or blank in .env.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    measured_wpm = _measure_pace_wpm(transcript.get("words", []), transcript.get("duration", 0))

    # Frame filenames are part of the payload so the model can name real frames
    # in exemplars (not invent filenames). WHY: exemplars must point at frames
    # that actually exist on disk, or the conditioning stage can't surface them.
    frame_names = [d.get("frame") for d in descriptions if d.get("frame")]

    user_payload = {
        "measured_pace_wpm": measured_wpm,
        "available_frame_filenames": frame_names,
        "transcript_excerpt": transcript.get("text", "")[:6000],
        "frame_descriptions": descriptions,
    }

    prompt = (
        "You are extracting a reusable, ACTIONABLE STYLE PROFILE from a "
        "3Blue1Brown-style math explainer video. The profile will DRIVE "
        "generation of a new video, so it must be concrete, not vague. You are "
        "given (1) a measured speaking pace, (2) the list of frame filenames "
        "available on disk, (3) a transcript excerpt, and (4) structured "
        "per-frame visual descriptions.\n\n"
        "Produce a SINGLE JSON object matching EXACTLY this schema (no markdown, "
        "no commentary):\n\n" + _SCHEMA_HINT + "\n\n"
        "Rules:\n"
        "- Use the provided measured_pace_wpm verbatim for audio.pace_wpm.\n"
        "- audio.pause_pattern: describe the rhythm of pauses; if you can, give a "
        "rough pause length in milliseconds (e.g. 'brief ~400ms pause after each "
        "key claim').\n"
        "- Ground palette hex values in the frame descriptions' palettes.\n"
        "- motion_vocabulary: the recurring animation moves you infer "
        "(e.g. 'morph equation', 'fade in label', 'draw axes').\n"
        "- style_descriptors: 3-5 REGISTER-GROUNDED adjectives describing the "
        "narration voice (e.g. 'calm', 'conversational', 'curious', 'precise'). "
        "Base them on the actual transcript wording, not generic praise.\n"
        "- pedagogy.intent_sequence: 3-5 ORDERED, NAMED teaching intents in "
        "kebab-case that capture how the lesson is structured "
        "(e.g. 'motivate-with-puzzle', 'build-intuition-geometrically', "
        "'formalize'). This is a checklist, not a vibe.\n"
        "- exemplars: 2-3 entries. Each MUST contain a VERBATIM transcript_snippet "
        "(copy the exact words from the transcript excerpt, one short sentence) "
        "AND a 'frame' chosen ONLY from available_frame_filenames, plus the "
        "named techniques it illustrates. Concrete demonstrations are the "
        "load-bearing signal.\n"
        "- Output ONLY the JSON object.\n\n"
        "INPUT:\n" + json.dumps(user_payload, indent=2)
    )

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=_FUSION_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    # Be forgiving about stray fences / prose around the JSON object.
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    profile = json.loads(raw)

    # Belt-and-suspenders: force the measured pace in even if the model drifted.
    profile.setdefault("audio", {})["pace_wpm"] = measured_wpm

    # Validate the ENRICHED fields are present and actionable. WHY: the whole
    # point of Phase 2 is that the profile DRIVES generation, so a profile that
    # silently dropped style_descriptors / exemplars / intent_sequence is a
    # broken artifact, not a degraded one. Fail loud here, not downstream.
    descriptors = profile.get("style_descriptors") or []
    intents = (profile.get("pedagogy") or {}).get("intent_sequence") or []
    exemplars = profile.get("exemplars") or []
    if not descriptors:
        raise ValueError("fused profile missing style_descriptors")
    if not intents:
        raise ValueError("fused profile missing pedagogy.intent_sequence")
    if not exemplars or not any(e.get("transcript_snippet") for e in exemplars):
        raise ValueError("fused profile missing exemplars with transcript_snippet")

    out_path = output_dir / f"{video_id}.json"
    out_path.write_text(json.dumps(profile, indent=2))

    return {"path": out_path, "profile": profile}


def _video_id_from_url(video_url: str) -> str:
    """Best-effort YouTube id from a URL. WHY: lets us check for cached
    transcript/frames before paying to re-download or re-run Whisper."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", video_url)
    if m:
        return m.group(1)
    # Fall back to the trailing path segment (already an id, or a local stem).
    return Path(video_url).stem


def extract_profile(video_url: str, reuse_cache: bool = True) -> dict:
    """End-to-end: video URL -> enriched Style Profile JSON.

    Runs download -> transcribe -> frames -> describe -> fuse. This is the
    Phase 2 entrypoint invoked by `python -m learnmorph.profile <url>`.

    WHY reuse_cache (default True):
    - Whisper transcription and frame sampling are deterministic and expensive
      (CPU-minutes). If a transcript JSON and sampled frames already exist on
      disk for this video id, reuse them. Only the Gemini describe + Claude
      fuse steps actually need to re-run to (re)build the profile. This also
      means a fresh profile can be built without re-downloading a 25MB MP4.

    Returns
    -------
    dict with keys:
        path     -> Path to the profile JSON
        profile  -> the parsed profile dict
        video_id -> the YouTube id
    """
    video_id = _video_id_from_url(video_url)

    cached_transcript = Path("outputs/transcripts") / f"{video_id}.json"
    cached_frame_dir = Path("outputs/frames") / video_id

    transcript: dict
    frame_paths: list[Path]

    have_transcript = reuse_cache and cached_transcript.exists()
    cached_frames = sorted(cached_frame_dir.glob("*.jpg")) if reuse_cache else []
    have_frames = bool(cached_frames)

    # Bound the Gemini describe bill: Flash free-tier is ~20 req/day. If more
    # frames are cached, evenly subsample down to keep headroom under the cap.
    describe_cap = 12

    if have_transcript and have_frames:
        transcript = json.loads(cached_transcript.read_text())
        frame_paths = cached_frames
        if len(frame_paths) > describe_cap:
            step = len(frame_paths) / describe_cap
            frame_paths = [frame_paths[int(i * step)] for i in range(describe_cap)]
    else:
        # Cache miss for at least one signal: fall back to the full pipeline.
        dl = download_video(video_url)
        video_path = dl["path"]
        video_id = dl["id"]
        transcript = (
            json.loads(cached_transcript.read_text())
            if have_transcript
            else transcribe_audio(video_path)
        )
        frame_paths = cached_frames if have_frames else sample_frames(video_path)["frame_paths"]

    described = describe_frames(frame_paths)

    fused = fuse_profile(transcript, described["descriptions"], video_id)
    return {"path": fused["path"], "profile": fused["profile"], "video_id": video_id}


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=WUvTyaaNkzM"
    result = extract_profile(url)
    print(f"profile -> {result['path']}")
    print(json.dumps(result["profile"], indent=2)[:800])
