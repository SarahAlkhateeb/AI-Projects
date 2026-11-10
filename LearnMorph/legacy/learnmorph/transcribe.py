"""Stage — audio → text with word-level timestamps.

WHY faster-whisper (not openai-whisper):
- openai-whisper pulls a `torch` that pins `numpy<2`, which conflicts with
  manim's `numpy>=2.1` on this Intel macOS environment. faster-whisper is a
  CTranslate2 reimplementation of the SAME Whisper models — torch-free and
  NumPy-2 compatible — so it coexists with manim in one venv.

WHY word-level timestamps:
- Later stages (pace_wpm, pause_pattern in the Style Profile) need to know not
  just *what* was said but *when*. Word timings let us measure speaking pace and
  detect the long pauses 3b1b leaves after a key claim.

WHY small/base models:
- We only need a rough transcript to characterise pace and phrasing, not a
  publication-grade transcript. "base" is fast and good enough; "small" is the
  fallback when accuracy matters. CPU int8 keeps it light on an Intel Mac.
"""

import json
from pathlib import Path

from faster_whisper import WhisperModel


def transcribe_audio(
    video_path: Path,
    output_dir: Path = Path("outputs/transcripts"),
    model_size: str = "base",
) -> dict:
    """Transcribe a video's audio to text with per-word timestamps.

    Parameters
    ----------
    video_path : Path
        Path to the source MP4 (faster-whisper reads the audio track directly
        via its bundled decoder, so no separate WAV extraction is needed).
    output_dir : Path
        Where to write the transcript JSON. Created if absent.
    model_size : str
        Whisper model size — "base" (default) or "small".

    Returns
    -------
    dict with keys:
        path        -> Path to the saved transcript JSON
        text        -> full transcript text (str)
        words       -> list of {"word", "start", "end"} dicts
        duration    -> audio duration in seconds (float)
        word_count  -> number of words transcribed (int)
        language    -> detected language code (str)
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # CPU + int8: smallest memory footprint, no GPU assumptions. Fine for the
    # short clips we profile from.
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, info = model.transcribe(
        str(video_path),
        word_timestamps=True,
    )

    words: list[dict] = []
    text_parts: list[str] = []
    # segments is a generator — iterating it is what actually runs inference.
    for segment in segments:
        text_parts.append(segment.text)
        for w in segment.words or []:
            words.append(
                {
                    "word": w.word.strip(),
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                }
            )

    full_text = "".join(text_parts).strip()

    out_path = output_dir / f"{video_path.stem}.json"
    payload = {
        "text": full_text,
        "words": words,
        "duration": round(float(info.duration), 3),
        "language": info.language,
        "model_size": model_size,
    }
    out_path.write_text(json.dumps(payload, indent=2))

    return {
        "path": out_path,
        "text": full_text,
        "words": words,
        "duration": round(float(info.duration), 3),
        "word_count": len(words),
        "language": info.language,
    }


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/videos/WUvTyaaNkzM.mp4")
    result = transcribe_audio(src)
    print(f"transcript -> {result['path']}")
    print(f"words={result['word_count']} duration={result['duration']}s lang={result['language']}")
