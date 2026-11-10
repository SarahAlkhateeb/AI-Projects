# LearnMorph

Learns *how* a teacher teaches (pedagogical moves + visual style), then generates a
new lesson on a different topic in that style. Style profile is the product; the
renderer is swappable. v1 (Manim pipeline, June 2026) is in `legacy/` — read-only reference.

## Pipeline (v2, Nov 2026)

```
learnmorph.py          text:  corpus → move grammar → exemplars → plan → beats → script → blind test
learnmorph_video.py    video: beats → visual profile → storyboard (JSON props) → TTS → Remotion → frame judge
learnmorph_avatar.py   alt renderer: HeyGen stock presenter picture-in-picture (lecturer-style teachers)
remotion/              8 props-driven templates; ALL animation code lives here, never per-lesson
```
Every stage is produce → judge → retry (max 3); state in `runs/<id>/`; reruns resume.
Steps: `BRIEF_claude_code.md`. Rationale: project memory `overview`.

## Do not relitigate

1. Style = move grammar (labelled beats, counts, verbatim examples), never adjectives.
2. Contrastive exemplars (teacher excerpt vs generic rewrite) in every generation prompt.
3. Beat-level generation, N candidates, judge reranks. Never whole-script in one call.
4. LLM fills template **props** (JSON). It never writes animation code.
5. Never clone the source teacher's voice or likeness. Neutral TTS / stock avatar only.
6. No rendering work until the two-teacher blind test ≥ 90%.

## How to decide

- Verify library APIs against official docs before writing code (Remotion, HeyGen, Anthropic). Don't guess.
- Smallest diff that passes the gate. Cut anything that wouldn't cause a real problem if removed.
- A gate failing 3× usually means the *grammar/exemplars* are wrong, not the writer prompt.
- When uncertain, pick what's easier to debug at 2am.

## Stack

Python 3.11+ via `uv`; `pyproject.toml` is the dep source of truth; `ruff`.
Node 18+ for `remotion/` (`npm install` there). ffmpeg. Models via `LM_WRITER_MODEL` / `LM_JUDGE_MODEL`
(default `claude-sonnet-5`); judge must differ from writer for the blind test.

## Commands

```bash
uv sync
uv run learnmorph.py --config config.json --run demo1                  # text stage → validation
uv run learnmorph_video.py --run demo1 --teacher 3b1b --source-video <url>
uv run learnmorph_avatar.py --run demo1 --teacher lecturer --avatar-id <id> --voice-id <id>
cd remotion && npx remotion render src/index.ts Lesson out/demo.mp4     # smoke test, no LLM calls
```

## Don't

Commit `.env`, `runs/*/video`, `remotion/node_modules`. Free-form animation code. Source-voice cloning.
