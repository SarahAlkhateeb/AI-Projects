"""
LearnMorph TTS stage (standalone — no Anthropic SDK). Reads runs/<id>/storyboards/<teacher>.json,
synthesizes each shot's phrase, measures durations, writes:
  remotion/public/audio/<teacher>/beat_<i>.mp3   (concatenated per beat)
  runs/<id>/storyboards/<teacher>_timed.json     (shots with start_s/end_s, beats with duration_s/audio)

Pacing: gap after a shot depends on how its phrase ends (sentence end -> longer breath), and every beat
ends with a long pause. Speaking speed varies by beat type so the delivery isn't monotone.

Engines: ElevenLabs (ELEVENLABS_API_KEY) -> kokoro-onnx (KOKORO_ONNX_MODEL/KOKORO_ONNX_VOICES) -> macOS say.

    python tts_vm.py --run demo1 --teacher 3b1b [--voice af_heart] [--mode sentence|phrase] [--engine chatterbox]

Modes: sentence (default) synthesizes each whole sentence once so intonation runs across shots, then splits
the clip across its shots by character count (the kokoro model here reports no phoneme durations).
phrase = old behaviour, one clip per shot phrase.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
GAP_SHORT, GAP_LONG, BEAT_TAIL = 0.30, 0.60, 1.25

# slower = more deliberate. Varies delivery across the lesson.
BEAT_SPEED = {"hook": 0.94, "misconception": 0.96, "concrete_example": 1.0, "visual": 0.96,
              "generalize": 0.94, "reprise": 0.96, "caveat": 0.92, "bridge": 1.0,
              "exercise": 0.97, "meta": 0.94}


def sh(cmd, check=True):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"{cmd}\n{p.stderr[-1500:]}")
    return p.stdout


def dur(path):
    return float(sh(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{path}"').strip())


_kokoro = None


def tts(text, wav, voice, speed):
    global _kokoro
    if ENGINE == "chatterbox":
        return tts_chatterbox(text, wav)
    key = os.getenv("ELEVENLABS_API_KEY")
    if key:
        try:
            import urllib.request
            req = urllib.request.Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice or '21m00Tcm4TlvDq8ikWAM'}",
                data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                                 "voice_settings": {"stability": 0.45, "similarity_boost": 0.75}}).encode(),
                headers={"xi-api-key": key, "Content-Type": "application/json"})
            mp3 = wav.with_suffix(".src.mp3")
            mp3.write_bytes(urllib.request.urlopen(req, timeout=120).read())
            sh(f'ffmpeg -y -loglevel error -i "{mp3}" -ar 24000 -ac 1 "{wav}"'); mp3.unlink()
            return "elevenlabs"
        except Exception as e:
            print(f"  elevenlabs failed ({str(e)[:80]}); trying kokoro-onnx")
    model, voices = os.getenv("KOKORO_ONNX_MODEL"), os.getenv("KOKORO_ONNX_VOICES")
    if model and voices and Path(model).exists():
        import soundfile as sf
        from kokoro_onnx import Kokoro
        if _kokoro is None:
            _kokoro = Kokoro(model, voices)
        samples, sr = _kokoro.create(text, voice=voice or "af_heart", speed=speed)
        sf.write(wav, samples, sr)
        return "kokoro-onnx"
    aiff = wav.with_suffix(".aiff")
    sh(f'say -v "{voice or "Daniel"}" -r {int(150 * speed)} -o "{aiff}" "{text.replace(chr(34), chr(39))}"')
    sh(f'ffmpeg -y -loglevel error -i "{aiff}" -ar 24000 -ac 1 "{wav}"'); aiff.unlink()
    return "say"


ENGINE = None


def tts_chatterbox(text, wav, exaggeration=0.5, cfg_weight=0.5):
    # NOT RUN in this environment (weights live on Hugging Face, blocked in the VM). API per the official
    # README (resemble-ai/chatterbox): ChatterboxTTS.from_pretrained(device) / .generate(text, exaggeration=,
    # cfg_weight=) -> torch tensor, .sr. Install separately: pip install chatterbox-tts. Voice cloning optional
    # via audio_prompt_path.
    global _cb
    import torch, torchaudio as ta
    from chatterbox.tts import ChatterboxTTS
    if _cb is None:
        _cb = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    ta.save(str(wav), _cb.generate(text, exaggeration=exaggeration, cfg_weight=cfg_weight), _cb.sr)
    return "chatterbox"


_cb = None


def gap_after(phrase):
    return GAP_LONG if phrase.rstrip().endswith((".", "?", "!")) else GAP_SHORT


def silence(work, seconds):
    f = work / f"sil_{int(seconds*100)}.wav"
    if not f.exists():
        sh(f'ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=24000:cl=mono -t {seconds} "{f}"')
    return f


def group_sentences(shots):
    """Consecutive shots whose phrases together form one sentence (ends with . ? or !)."""
    groups, cur = [], []
    for k, s in enumerate(shots):
        cur.append(k)
        if s["phrase"].rstrip().endswith((".", "?", "!")):
            groups.append(cur); cur = []
    return groups + ([cur] if cur else [])


def render_beat(b, work, audio_dir, mp3, mode, voice, speed):
    """Synthesize one beat, set shot start_s/end_s + beat duration_s, write mp3. Returns engine name."""
    t, lines, engine = 0.0, [], None
    shots = b["shots"]
    groups = [[k] for k in range(len(shots))] if mode == "phrase" else group_sentences(shots)
    for ks in groups:
        text = " ".join(shots[k]["phrase"].strip() for k in ks)
        tag = f"s{ks[0]}" if mode == "phrase" else f"g{ks[0]}-{ks[-1]}"  # distinct cache names per mode
        wav = work / f"b{b['i']}_{tag}_{int(speed*100)}.wav"
        if not wav.exists():
            engine = tts(text, wav, voice, speed)
        d = dur(wav)
        g = gap_after(shots[ks[-1]]["phrase"])
        # split clip + trailing gap across shots; no gap inside a sentence. Shot share = character share.
        total = sum(len(shots[k]["phrase"].strip()) for k in ks)
        acc = 0
        for k in ks:
            share = len(shots[k]["phrase"].strip())
            a0, acc = acc, acc + share
            s0 = t + d * a0 / total
            s1 = t + d * acc / total
            if k == ks[-1]:
                s1 = t + d + g
            shots[k]["start_s"], shots[k]["end_s"] = round(s0, 2), round(s1, 2)
        t += d + g
        lines += [f"file '{wav.resolve()}'", f"file '{silence(work, g).resolve()}'"]
    lines.append(f"file '{silence(work, BEAT_TAIL).resolve()}'")
    b["duration_s"] = round(t + BEAT_TAIL, 2)
    shots[-1]["end_s"] = b["duration_s"]
    lst = work / f"b{b['i']}_{mode}.txt"
    lst.write_text("\n".join(lines))
    sh(f'ffmpeg -y -loglevel error -f concat -safe 0 -i "{lst}" -q:a 2 "{mp3}"')
    # checks: contiguous, and times sum to the actual audio length
    assert shots[0]["start_s"] == 0
    for x, y in zip(shots, shots[1:]):
        assert x["end_s"] == y["start_s"], (b["i"], x["end_s"], y["start_s"])
    real = dur(mp3)
    # mp3 encoding adds ~50 ms of encoder padding; the file length is the truth, so snap the beat end to it.
    assert abs(shots[-1]["end_s"] - real) < 0.1, f"beat {b['i']}: timed {shots[-1]['end_s']} vs mp3 {real}"
    shots[-1]["end_s"] = b["duration_s"] = round(real, 2)
    assert abs(shots[-1]["end_s"] - real) < 0.05
    return engine


def main():
    global ENGINE
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--teacher", required=True)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--mode", choices=["sentence", "phrase"], default="sentence")
    ap.add_argument("--engine", choices=["default", "chatterbox"], default="default")
    ap.add_argument("--only-beat", type=int, default=None, help="render one beat only (A/B); needs --audio-out")
    ap.add_argument("--audio-out", default=None)
    a = ap.parse_args()
    ENGINE = a.engine
    run = Path("runs") / a.run
    sb = json.loads((run / "storyboards" / f"{a.teacher}.json").read_text())
    audio_dir = HERE / "remotion" / "public" / "audio" / a.run / a.teacher
    work = run / "tts_work" / a.teacher
    work.mkdir(parents=True, exist_ok=True)

    if a.only_beat is not None:
        b = next(x for x in sb["beats"] if x["i"] == a.only_beat)
        out = Path(a.audio_out); out.parent.mkdir(parents=True, exist_ok=True)
        render_beat(b, work, audio_dir, out, a.mode, a.voice, BEAT_SPEED.get(b["beat"], 0.97))
        print(f"wrote {out} ({b['duration_s']}s, {a.mode})")
        return

    audio_dir.mkdir(parents=True, exist_ok=True)
    for b in sb["beats"]:
        speed = BEAT_SPEED.get(b["beat"], 0.97)
        engine = render_beat(b, work, audio_dir, audio_dir / f"beat_{b['i']}.mp3", a.mode, a.voice, speed)
        b["audio"] = f"audio/{a.run}/{a.teacher}/beat_{b['i']}.mp3"
        print(f"beat {b['i']}: {len(b['shots'])} shots, {b['duration_s']}s, speed {speed}, {engine}", flush=True)

    out = run / "storyboards" / f"{a.teacher}_timed.json"
    out.write_text(json.dumps(sb, indent=2))
    print(f"done: {out} ({sum(b['duration_s'] for b in sb['beats']):.0f}s total)")


if __name__ == "__main__":
    main()
