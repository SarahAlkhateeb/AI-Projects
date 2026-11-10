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
matches the real teacher. The recipe-free evaluation below measures this directly.

## Evaluation against the real teachers (`eval/`, 2026-11-10)

Judge claude-opus-5-5, writer claude-sonnet-5-5. Full tables and limitations: `eval/report.md`.

- Generated text was picked as the real human 0 of 40 times (also 0 of 40 after filler words were removed
  from the real text). The judge never mistakes the generated text for the human, and the unstyled control
  fares no better (0 of 12).
- An unstyled control (plain Sonnet explainer, no style information) was labelled 3b1b 20 of 20 times. So the
  3b1b attribution result (40/40 overall, 20/20 for 3b1b scripts) carries no information: any polished LLM
  script sounds like 3b1b to this judge.
- The lecturer (Khan Academy style) attribution of 20 of 20 is real signal, since it holds against that pull.
- Beat frequencies move toward the target teacher, weakly: 3 of 4 scripts are closer to their own teacher on
  both cosine and JSD, and 7 of 8 comparisons beat the unstyled control. Transition order does not move toward
  the target, and the metric fails to separate the real teachers either, so it is uninformative at this data size.
- The earlier 10/10 blind test measured recipe-following, not likeness to the human.
- Ceiling check: real held-out text from either teacher is identified 20 of 20, so the task itself is easy.

Limitations: writer and judge are the same model family; LUAR check written but not run; only 3 real
transcripts per teacher (lecturer about 3,300 words), all used to build the grammars, so there is no held-out
real text; small n (10 trials per script, trials reuse the same 4 scripts); topic confound (demo1 is calculus,
which both teachers teach); test 4 is a pairwise forced choice, easier than spotting a fake alone, and the
judge may recognise real transcripts from pretraining; real text had names replaced and one lecturer file is
raw auto-captions; beat labels come from one Sonnet segmentation per text.

## In progress

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
