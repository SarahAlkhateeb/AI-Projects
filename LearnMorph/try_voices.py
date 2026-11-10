"""
Voice trial: the same passage (misleading-charts lesson, beat 1) spoken by several engines, so they can be
compared by ear. Output: runs/voice_trial/*.wav|mp3 plus log.txt. Each engine is independent: one failing
does not stop the others.

Run on the Mac itself (needs Hugging Face and Google reachable):  double-click try_voices.command
Engines:
  1 Kokoro (current)        copied from runs/demo2/tts_ab if present
  2 Chatterbox, default     exaggeration 0.5, cfg_weight 0.5   (pip: chatterbox-tts, MIT; README: Python 3.11)
  3 Chatterbox, expressive  exaggeration 0.7, cfg_weight 0.3   (values from the project README's tips)
  4 Gemini TTS, "curious"   gemini-3.8-flash-tts, delivery direction in speech_metadata.style
  5 Gemini TTS, "sketching" same model, a conversational direction
API shapes checked on 2026-11-10 against github.com/resemble-ai/chatterbox README and
ai.google.dev/gemini-api/docs/generate-content/speech-generation. Nothing here was run before delivery.
"""
import base64, json, os, re, shutil, traceback, urllib.error, urllib.request
from pathlib import Path

OUT = Path("runs/voice_trial"); OUT.mkdir(parents=True, exist_ok=True)
sb = json.loads(Path("runs/demo2/storyboards/3b1b.json").read_text())
beat = sb["beats"][0]
TEXT = re.sub(r"\s+", " ", beat.get("narration") or " ".join(s["phrase"] for s in beat["shots"])).strip()
SENTENCES = [s.strip() for s in re.findall(r"[^.!?]+[.!?]+[\"')\]]*", TEXT) if s.strip()] or [TEXT]
print(f"passage: {len(TEXT.split())} words, {len(SENTENCES)} sentences\n{TEXT}\n")
results = {}


def attempt(name, fn):
    try:
        fn(); results[name] = "ok"; print(f"[ok]     {name}")
    except Exception as e:  # report and carry on with the other engines
        results[name] = f"FAILED: {type(e).__name__}: {str(e)[:300]}"
        print(f"[failed] {name}: {results[name]}"); traceback.print_exc()


def kokoro_copy():
    src = Path("runs/demo2/tts_ab/beat1_sentence.mp3")
    if not src.exists():
        raise FileNotFoundError(f"{src} not found")
    shutil.copy(src, OUT / "1_kokoro_current.mp3")


_cb = {}


def chatterbox_model():
    if "m" in _cb:
        return _cb["m"]
    import torch
    from chatterbox.tts import ChatterboxTTS
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        m = ChatterboxTTS.from_pretrained(device=device)
    except Exception as e:
        print(f"  load on {device} failed ({str(e)[:120]}); retrying with map_location, then cpu")
        orig = torch.load
        torch.load = lambda *a, **k: orig(*a, **{"map_location": torch.device(device), **k})
        try:
            m = ChatterboxTTS.from_pretrained(device=device)
        except Exception:
            torch.load = lambda *a, **k: orig(*a, **{"map_location": torch.device("cpu"), **k})
            m = ChatterboxTTS.from_pretrained(device="cpu")
        finally:
            torch.load = orig
    _cb["m"] = m
    return m


def chatterbox(tag, exaggeration, cfg_weight):
    import torch, torchaudio as ta
    m = chatterbox_model()
    parts = []
    for s in SENTENCES:
        wav = m.generate(s, exaggeration=exaggeration, cfg_weight=cfg_weight).detach().cpu()
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)
        parts += [wav, torch.zeros(1, int(m.sr * 0.4))]
    ta.save(str(OUT / f"{tag}.wav"), torch.cat(parts, dim=1), m.sr)


def gemini(tag, voice, style):
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY / GOOGLE_API_KEY in the environment")
    body = {"contents": [{"role": "user", "parts": [{"text": TEXT, "speech_metadata": {"style": style}}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"voice": voice}}}}
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent",
        data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    part = data["candidates"][0]["content"]["parts"][0]
    (OUT / f"{tag}.wav").write_bytes(base64.b64decode(part["inlineData"]["data"]))


attempt("1 kokoro (current)", kokoro_copy)
attempt("2 chatterbox default", lambda: chatterbox("2_chatterbox_default", 0.5, 0.5))
attempt("3 chatterbox expressive", lambda: chatterbox("3_chatterbox_expressive", 0.7, 0.3))
attempt("4 gemini curious", lambda: gemini(
    "4_gemini_curious", "Sulafat",
    "Curious and unhurried, thinking aloud with a friend. Quiet delight at the surprising part. Clear pauses between ideas."))
attempt("5 gemini sketching", lambda: gemini(
    "5_gemini_sketching", "Charon",
    "Friendly and conversational, slightly improvised, like talking while sketching on a whiteboard. Relaxed pace."))

(OUT / "results.json").write_text(json.dumps(results, indent=2))
print("\nSummary:"); [print(f"  {k}: {v}") for k, v in results.items()]
