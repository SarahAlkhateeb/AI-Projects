# LearnMorph style eval: does the output sound like the REAL teacher?

Judge: claude-opus-5-5 (writer: claude-sonnet-5-5). 166 API calls, all cached in `cache/` (a rerun costs 0 calls).
Fixed seeds. Raw per-trial rows, including the judge's one-line reasons, are in `results.json`.

## Results in plain words

| Test | Result | What it means |
|---|---|---|
| 1. Attribution, no recipe shown | 40/40 correct (10/10 for each of the 4 scripts), mean confidence 81-85 | Shown real excerpts only, the judge always picks the intended teacher. Read this against test 3. |
| 2. Ceiling (held-out real chunk from another video) | 20/20, mean confidence 91 | The task is easy: real text from either teacher is always identified. |
| 3. Unstyled control (plain Sonnet explainer, no style info) | 20/20 assigned to **3b1b**, mean confidence 68-78 | Strong judge bias: any polished LLM script "sounds like 3b1b". So the 3b1b result in test 1 (20/20) proves nothing. The lecturer result (20/20 against this pull) is the real signal in test 1. |
| 4. Real vs generated (~300 words each, same teacher) | Generated picked as the real human **0/40** (raw) and **0/40 after the real chunk was cleaned of filler words**; unstyled: 0/12. Confidence ~90 | The judge never mistakes the generated text for the human. 50% would mean indistinguishable. It still reads as machine-written, and no more human than the unstyled control. |
| 5. Beat structure (no judge) | Beat-frequency: 3 of 4 scripts closer to their own teacher on both cosine and JSD (demo2/3b1b is a tie on cosine and closer to the lecturer on JSD); 7 of 8 comparisons beat the unstyled control. Transition bigrams: all 4 scripts closer to the lecturer | Lesson *shape* (which beat types and how often) moves toward the target teacher, weakly. Transition order does not, but the bigram metric fails to separate the real teachers too (2 of 3 real 3b1b videos are closer to the lecturer on leave-one-out), so it is uninformative at this data size. |

## Honest conclusions

1. **It does not sound like the real teacher.** The judge separates generated from real 40/40 times, even after the
   real transcript's filler words are removed. Its reasons point at style, not just disfluency: generated text is
   "tidily scripted", "packs in neat numbers", uses repeated tics ("there's nothing special about" x3), and stages the
   teacher's habits ("a tidy staged colour correction": the lecturer scripts imitate Sal's "let me pick a red--
   actually, green" so often it reads as caricature).
2. **It does sound like the right one of the two.** The lecturer-styled scripts are pulled to the lecturer 20/20 even
   though the judge's default for LLM text is 3b1b, and beat frequencies move toward the target. The 3b1b-styled
   scripts cannot be told apart from "generic LLM explainer" by test 1 or test 3; 3b1b is roughly where Sonnet
   already sits.
3. The old 10/10 validation measured recipe-following, not likeness to the human. That matches the "authorship gap"
   failure (arXiv 2604.26460).

## Limitations

- Same model family for writer and judge (Sonnet / Opus). A judge from another provider plugs in at `judge()` via
  `LM_JUDGE_PROVIDER` (not implemented). LUAR (`luar_score.py`) is a non-LLM check, written but **not run** (Hugging Face blocked here).
- Tiny real corpus: 3 transcripts per teacher (lecturer ~3,300 words). The grammars were built from all of them,
  so there is no held-out real text the generator never "saw" through its grammar.
- Small n: 10 trials per script, 5 pairs per script in test 4, one beat segmentation per text (no variance estimate).
  Trials reuse the same 4 scripts, so they are not independent samples of the generator.
- Topic confound: demo1 (derivative of e^x) is calculus, which both teachers teach in the corpus.
- Test 4 is a pairwise forced choice, which is easier than spotting a fake on its own. The judge sometimes names
  "3Blue1Brown"/"Sal Khan", so it may recognise real transcripts from pretraining.
- Real text: names (Grant, Sal, Khan Academy) replaced with "[name]". One lecturer file (N2PpRnFqnqY) is raw
  auto-captions with no punctuation; Sonnet added punctuation only (word count 1250 -> 1249) so missing punctuation
  wasn't a trivial tell. The "cleaned" test-4 variant is also a Sonnet edit.
- Beat labels come from Sonnet with the learnmorph segmentation prompt. Fresh re-segmentation agrees with the stored
  grammars' beat frequencies at cosine 0.97 (3b1b) and 0.89 (lecturer).

<!-- generated tables below: rewritten on every run -->
# LearnMorph style eval — raw tables

API calls this run: {'cached': 167}. Errors: none

## Test 1 — recipe-free attribution (generated scripts)

| item | correct | n | acc | p_one_sided | mean_conf |
|---|---|---|---|---|---|
| demo2/3b1b | 10 | 10 | 1.0 | 0.001 | 85.4 |
| demo1/3b1b | 10 | 10 | 1.0 | 0.001 | 83.0 |
| demo2/lecturer | 10 | 10 | 1.0 | 0.001 | 80.6 |
| demo1/lecturer | 10 | 10 | 1.0 | 0.001 | 83.2 |

## Test 2 — ceiling (held-out real chunk, other video)

| item | correct | n | acc | p_one_sided | mean_conf |
|---|---|---|---|---|---|
| real/3b1b | 10 | 10 | 1.0 | 0.001 | 90.8 |
| real/lecturer | 10 | 10 | 1.0 | 0.001 | 90.6 |

## Test 3 — unstyled control (how often judged as 3b1b)

| item | picked_3b1b | n | mean_conf |
|---|---|---|---|
| unstyled/demo1 | 10 | 10 | 77.8 |
| unstyled/demo2 | 10 | 10 | 68.4 |

## Test 4 — real vs generated (rate = generated picked as the real human; 0.5 = indistinguishable)

| item | generated_picked_as_real | n | rate | mean_conf |
|---|---|---|---|---|
| demo2/3b1b [raw] | 0 | 5 | 0.0 | 91.0 |
| demo2/3b1b [cleaned] | 0 | 5 | 0.0 | 91.8 |
| demo1/3b1b [raw] | 0 | 5 | 0.0 | 91.0 |
| demo1/3b1b [cleaned] | 0 | 5 | 0.0 | 91.4 |
| demo2/lecturer [raw] | 0 | 5 | 0.0 | 91.0 |
| demo2/lecturer [cleaned] | 0 | 5 | 0.0 | 89.6 |
| demo1/lecturer [raw] | 0 | 5 | 0.0 | 88.8 |
| demo1/lecturer [cleaned] | 0 | 5 | 0.0 | 88.8 |
| unstyled/demo1 [raw] | 0 | 6 | 0.0 | 91.5 |
| unstyled/demo2 [raw] | 0 | 6 | 0.0 | 91.8 |

## Test 5 — beat structure (cos: higher = closer; jsd: lower = closer)

| item | freq_cos_3b1b | freq_jsd_3b1b | freq_cos_lecturer | freq_jsd_lecturer | bigram_cos_3b1b | bigram_jsd_3b1b | bigram_cos_lecturer | bigram_jsd_lecturer |
|---|---|---|---|---|---|---|---|---|
| demo2/3b1b | 0.864 | 0.128 | 0.858 | 0.088 | 0.403 | 0.625 | 0.549 | 0.535 |
| demo1/3b1b | 0.863 | 0.093 | 0.829 | 0.145 | 0.194 | 0.781 | 0.46 | 0.541 |
| demo2/lecturer | 0.841 | 0.175 | 0.952 | 0.042 | 0.338 | 0.688 | 0.508 | 0.528 |
| demo1/lecturer | 0.684 | 0.251 | 0.874 | 0.127 | 0.133 | 0.842 | 0.36 | 0.634 |
| unstyled/demo1 | 0.734 | 0.273 | 0.858 | 0.149 | 0.391 | 0.668 | 0.693 | 0.427 |
| unstyled/demo2 | 0.84 | 0.093 | 0.733 | 0.154 | 0.402 | 0.557 | 0.488 | 0.579 |

### Leave-one-out real transcripts (what a real match looks like)

| item | freq_cos_3b1b | freq_jsd_3b1b | freq_cos_lecturer | freq_jsd_lecturer | bigram_cos_3b1b | bigram_jsd_3b1b | bigram_cos_lecturer | bigram_jsd_lecturer |
|---|---|---|---|---|---|---|---|---|
| 3b1b/WUvTyaaNkzM | 0.776 | 0.121 | 0.568 | 0.246 | 0.245 | 0.713 | 0.104 | 0.891 |
| 3b1b/aircAruvnKk | 0.914 | 0.034 | 0.825 | 0.157 | 0.446 | 0.506 | 0.452 | 0.611 |
| 3b1b/spUNpyF58BY | 0.828 | 0.097 | 0.82 | 0.149 | 0.307 | 0.638 | 0.393 | 0.58 |
| lecturer/N2PpRnFqnqY | 0.802 | 0.141 | 0.866 | 0.106 | 0.317 | 0.69 | 0.184 | 0.776 |
| lecturer/bRZmfc1YFsQ | 0.699 | 0.312 | 0.742 | 0.232 | 0.281 | 0.807 | 0.046 | 0.927 |
| lecturer/rAof9Ld5sOg | 0.762 | 0.202 | 0.904 | 0.103 | 0.32 | 0.685 | 0.28 | 0.693 |

Stored grammar beat_frequency vs fresh re-segmentation (cosine): {'3b1b': 0.97, 'lecturer': 0.889}
