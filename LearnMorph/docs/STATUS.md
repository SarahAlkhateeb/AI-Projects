# LearnMorph status

Snapshot of the baseline commit. Numbers come from the committed run files.

## Where it stands

- v2 text pipeline runs end to end for two teachers (`3b1b`, `lecturer`) on the topic in `config.json`
  ("Why does the derivative of e^x equal itself?"). Run `demo1`.
- v2 video pipeline (visual profile, phrase-shot storyboard, TTS, Remotion render, vision QA) has run for
  `demo1` (both teachers) and `demo2` (3b1b only; a different topic about misleading bar charts).
  Which videos exist on disk cannot be checked from the repository: see `runs/*/log.md`.
- Avatar renderer (`learnmorph_avatar.py`) is written; no run of it is recorded in the logs.
- The v1 Manim pipeline is archived in `legacy/`.

## Numbers

| Measure | Result | Source |
|---|---|---|
| Blind test, demo1 | 10/10 correct (accuracy 1.0, verdict PASS) | `runs/demo1/validation/report.json` |
| Grammar cosine similarity, 3b1b vs lecturer | 0.903 | `runs/demo1/log.md` |
| Shots passing visual QA, demo1 3b1b, round 3 | 28 / 63 | `runs/demo1/video/3b1b_qa_r3.json` |
| Shots passing visual QA, demo1 lecturer, round 3 | 42 / 59 | `runs/demo1/video/lecturer_qa_r3.json` |
| Shots passing visual QA, demo2 3b1b, round 3 | 35 / 74 | `runs/demo2/video/3b1b_qa_r3.json` |

Pass rule: shot average >= 3.7 and shot minimum >= 3. QA improved across rounds 1 to 3 in all three
runs but none reached a full pass; every video run ended at "max rounds ... with remaining issues".
The visual-profile and storyboard judge gates also ended with "gate failed; keeping best" in the demo1 log,
and the lecturer grammar gate failed after 3 rounds (best score 3.67 kept).

## Known weakness: the blind test is circular

The blind test uses a Claude judge shown scripts written from Claude-written grammars. A 10/10 score
shows that the two generated styles are distinguishable from each other. It does not show that either
matches the real teacher. An honest evaluation against the real teachers is in progress.

## In progress

- Evaluation that compares against the real teachers' material.
- Chart templates (demo2 uses a `plot` template for bar charts; its QA notes flag truncated bars and axes).
- Sentence-level narration (`tts_vm.py --mode sentence`, so intonation runs across shots).

## Other open items

- The `lecturer` demo1 storyboard scored 2.67 to 3.33 on the storyboard gate and its early render had 0/7
  frames passing; later phrase-shot runs reached 42/59.
- TTS in logged runs fell back to macOS `say` after ElevenLabs returned HTTP 402.
- The 3b1b reference video download failed with HTTP 403 in one logged run (profile inferred without frames).
- Repository hygiene (found while preparing this commit): `pyproject.toml` still points hatch at a
  `learnmorph` package that now lives in `legacy/`, and `run_v2.command` calls
  `uv run learnmorph_video.py true`, which does not match the script's required arguments.
