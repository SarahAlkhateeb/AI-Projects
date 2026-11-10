# LearnMorph

LearnMorph learns *how* a teacher teaches (the order of their pedagogical moves, how they phrase them,
how their visuals look) and then writes and animates a new lesson on a different topic in that style.
The style profile is the product; the renderer is swappable.

Current state, numbers and open problems: [docs/STATUS.md](docs/STATUS.md). History: [docs/CHANGELOG.md](docs/CHANGELOG.md).
Working rules for contributors and for Claude Code: [CLAUDE.md](CLAUDE.md).

## Pipeline (v2)

Every stage is produce, then judge, then retry (up to 3 rounds). State is written to `runs/<run-id>/`
after each stage, so re-running resumes where it stopped.

**Text stage** (`learnmorph.py`)
1. Corpus: plain-text transcripts per teacher.
2. Move grammar: labelled beats, counts and verbatim examples (never adjectives).
3. Exemplars: teacher excerpts paired with generic rewrites, used as contrast in every prompt.
4. Plan: a beat sequence for the new topic.
5. Beats: N candidate drafts per beat, a judge reranks them.
6. Script: beats assembled into one script per teacher.
7. Blind test: a judge is shown the scripts and asked which teacher's style each matches.

**Video stage** (`learnmorph_video.py`, `tts_vm.py`, `remotion/`)
1. Visual profile: palette, fonts, layout and motion for the teacher (`visual.json`).
2. Phrase-shot storyboard: narration split into phrases, each with one template plus JSON props.
3. TTS (`tts_vm.py`): one clip per phrase or sentence; clip length sets shot length.
4. Remotion render: props-driven templates only. The LLM fills props and never writes animation code.
5. QA: stills from the render are scored by a vision judge, and the loop retries.

`learnmorph_avatar.py` is an alternative renderer (stock HeyGen presenter picture-in-picture) for
presenter-led teachers. It never clones the source teacher's face or voice.

## Setup

```bash
uv sync                          # Python 3.11+, deps from pyproject.toml
cp .env.example .env             # then fill in ANTHROPIC_API_KEY (others optional)
cd remotion && npm install       # Node 18+, plus ffmpeg on PATH
```

Env vars used by the code: `ANTHROPIC_API_KEY` (required), `LM_WRITER_MODEL`, `LM_JUDGE_MODEL`,
`LM_EFFORT`, `LM_CHROME`, `ELEVENLABS_API_KEY`, `KOKORO_ONNX_MODEL`, `KOKORO_ONNX_VOICES`, `HEYGEN_API_KEY`.

Run everything from the project root: paths such as `runs/` and `data/` are relative.

## Running each stage

```bash
# Text stage: transcripts in data/<teacher>/*.txt (see config.json). --stop-after: grammar|exemplars|plan|beats|assemble
uv run learnmorph.py --config config.json --run demo1

# Video: visual profile + storyboard (needs the Anthropic API)
uv run learnmorph_video.py --run demo1 --teacher 3b1b --source-video <url> --stop-after storyboard

# TTS (needs only ffmpeg and one of ElevenLabs / kokoro-onnx / macOS say)
python tts_vm.py --run demo1 --teacher 3b1b [--mode sentence|phrase] [--voice <name>]

# Render + vision QA (needs node and remotion/node_modules). --no-judge skips QA.
uv run learnmorph_video.py --run demo1 --teacher 3b1b --render-only

# Optional avatar renderer
uv run learnmorph_avatar.py --run demo1 --teacher lecturer --avatar-id <id> --voice-id <id>

# Remotion smoke test, no LLM calls
cd remotion && npx remotion render src/index.ts Lesson out/demo.mp4
```

`run_v2.command` (macOS double-click) repairs the remotion install and renders both demo videos.

## Where outputs land

| Path | Contents |
|---|---|
| `runs/<id>/log.md` | timestamped record of every stage and score |
| `runs/<id>/profiles/<teacher>/` | `move_grammar.json`, `visual.json` (plus `exemplars.json`, local only) |
| `runs/<id>/plans/`, `scripts/` | plan, beats (`*_beats.json`) and assembled script (`*.md`) |
| `runs/<id>/validation/report.json` | blind-test trials and accuracy |
| `runs/<id>/storyboards/` | `<teacher>.json`, `_timed.json` (after TTS), `_timed_phrase.json` |
| `runs/<id>/video/` | rendered `.mp4` (local only) and `*_qa_r<round>.json` QA scores |
| `remotion/public/audio/` | synthesized narration (local only) |

## What is in this repository

Code, docs, and text artefacts from runs `demo1` and `demo2`; the v1 Manim pipeline is under `legacy/`
(read-only reference). Not committed, and regenerated locally: teacher transcripts (`data/`), run corpora,
segmented transcripts, exemplars and reference frames (third-party teachers' material), rendered media,
audio, model files and `node_modules`.
