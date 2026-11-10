# LearnMorph status

Numbers come from the committed run files. Last updated 2026-11-10.

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
| Blind test, demo1 | 10/10 correct (accuracy 1.0, verdict PASS); measures recipe-following, see eval section | `runs/demo1/validation/report.json` |
| Blind test, demo2 | 10/10 correct (accuracy 1.0, verdict PASS); same caveat | `runs/demo2/validation/report.json` |
| Grammar cosine similarity, 3b1b vs lecturer | 0.903 | `runs/demo1/log.md` |
| Shots passing visual QA, demo1 3b1b, round 3 | 28 / 63 | `runs/demo1/video/3b1b_qa_r3.json` |
| Shots passing visual QA, demo1 lecturer, round 3 | 42 / 59 | `runs/demo1/video/lecturer_qa_r3.json` |
| Shots passing visual QA, demo2 3b1b, round 3 | 55 / 78 with the chart templates (35 / 74 before them) | `runs/demo2/video/3b1b_qa_r3.json` |
| Shots passing visual QA, demo2 lecturer, round 3 | 51 / 70 with the chart templates | `runs/demo2/video/lecturer_qa_r3.json` |

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

## Writer experiment: matching measured traits (2026-11-10)

Does LearnMorph sound like the real teacher? Not yet.

The writer now measures each teacher's real habits in code (`style_traits.py`): sentence length, how often
they ask questions, signposting, recaps. It gives every countable habit a budget at the teacher's real rate
and rejects drafts whose sentence length falls outside a band around the real value. Run `demo3` is the
misleading-charts topic written this way; `demo2` is the same topic before these changes.

| 3b1b / lecturer | real transcripts | before (`demo2`) | after (`demo3`) |
|---|---|---|---|
| Mean sentence length, words | 25.4 / 16.7 | 10.6 / 11.6 | 22.4 / 14.9 |
| Share of sentences over 30 words | 0.31 / 0.11 | 0.01 / 0.03 | 0.10 / 0.00 |
| Questions per 1,000 words | 3.1 / 7.2 | 16.4 / 13.6 | 3.3 / 6.0 |
| Habits used at more than 1.5 times the real rate | n/a | 7 / 4 | 0 / 1 |
| Restarts per 100 words | 0.25 / 2.03 | 0 / 0.57 | 0 / 0.30 |
| Beat-mix similarity, own teacher vs the other | n/a | 0.86 vs 0.86 ; 0.95 vs 0.84 | 0.86 vs 0.93 ; 0.83 vs 0.79 |
| Judge picks the right teacher of the two | n/a | 10/10, 10/10 | 10/10, 10/10 |
| Generated passage picked as the real one (lecturer) | n/a | 0 of 5 | 0 of 5 |

What moved: average sentence length and habit rates now match each teacher. What did not: sentence lengths
are too even (few long sentences, none starting with "And"), restarts stay rare, and the mix of beat types
got worse, with the 3b1b script now closer to the lecturer's mix. Shown one real passage and one generated
passage, the judge picked the real one every time across all variants tried. It cites lengths that are too
even, tidy structure and staged asides. Two other variants were tried and dropped or made optional: prompt
guidance to "write for speech" had no measurable effect, and reranking each beat with the excerpt-only judge
(`--honest-gate`) lengthened sentences but tripled the cost.

Limitations: three transcripts per teacher; small samples; writer and judge are from the same model family,
and the writer was tuned against that judge family; the judge recognises some real videos from its training
data, so the side-by-side test cannot be passed for a well-known teacher; the authorship-embedding check is
written but has not been run. Raw numbers: `eval/results_D.json`.

Next: enforce the spread of sentence lengths as well as the mean, enforce the beat mix in the plan, and
retire the recipe-based rubric that scores longer sentences down.

## In progress

- Narration: the delivery is still flat. `try_voices.py` renders one passage with several engines
  (current Kokoro, Chatterbox at two settings, Gemini TTS with two delivery directions) for a listening
  comparison. It has not been run yet.
- Video for `demo3` has not been made; the `demo2` videos use the earlier scripts.

## Other open items

- The `lecturer` demo1 storyboard scored 2.67 to 3.33 on the storyboard gate and its early render had 0/7
  frames passing; later phrase-shot runs reached 42/59.
- TTS in logged runs fell back to macOS `say` after ElevenLabs returned HTTP 402.
- The 3b1b reference video download failed with HTTP 403 in one logged run (profile inferred without frames).
- Repository hygiene (found while preparing this commit): `pyproject.toml` still points hatch at a
  `learnmorph` package that now lives in `legacy/`, and `run_v2.command` called
  `uv run learnmorph_video.py true` (removed since).
