# LearnMorph — Research Findings (June 2026)

Deep-research pass (106 agents, 114 extracted claims, 75 adversarial
verification votes → **61 upheld / 14 refuted**). Goal: find the *simplest
proven* techniques for LLM-driven 3Blue1Brown-style video generation and
pedagogical style transfer, and turn them into a build plan.

Every claim below survived 3-vote adversarial verification unless marked
⚠️ (contested / refuted-as-overreach). Sources are primary (arXiv / official
docs / project repos).

---

## TL;DR — the seven things that matter

1. **The #1 gap is that our Style Profile is *described*, not *consumed*.**
   Closing that loop (profile → script + template + TTS) is the single
   highest-leverage change. Everything else is secondary.
2. **Concrete exemplars beat abstract adjectives.** "calm, conversational"
   is interpreted inconsistently; 2–3 *verbatim snippets* from the source are
   not. The profile must carry real examples, not just descriptors.
3. **Operationalize pedagogy as a fixed, named scene-intent sequence**
   (puzzle → intuition → formalize), not a "be 3b1b" instruction. Structured
   pedagogy templates measurably beat free-text prompting.
4. **Our bounded Manim retry loop is the right pattern** (it's literally
   "RITL" in the literature). Two cheap upgrades: feed only the *last ~10
   lines* of the render error, and retrieve *Manim API doc snippets* into the
   repair prompt.
5. **Render success ≠ visual quality.** Add a one-shot VLM visual check on a
   rendered frame — layout defects are the #1 residual defect even at 94%
   render success.
6. **No-clone voice control is a solved, simple thing.** `say -r` (pace) +
   `[[slnc]]` (pauses) now; ElevenLabs v3 *audio tags* (descriptor-driven, no
   clone) later. Never the clone path.
7. **Our cross-family Gemini judge is validated.** Upgrade it with
   reason-before-score (G-Eval), concrete score anchors, and one cheap CLIP
   visual-similarity metric. Score orthogonal axes; never one aggregate.

---

## SQ1 — LLM→Manim reliability (state of the art)

| Project | What it proves | Number |
|---|---|---|
| **TheoremExplainAgent** (arXiv 2502.19400, ACL 2025) | Planner+coder agentic loop; planning as a *separate stage* is essential for long-form video | o3-mini: **93.8% render success**, 0.77 overall; bench = 240 theorems / 5 metrics |
| **Code2Video** (arXiv 2510.01174, ICML 2026) | Planner/Coder/Critic tri-agent; **+40%** over flat codegen; "scope-guided auto-fix" (line→block→global repair) = structured, not free-form | +40% on the TeachQuiz pedagogical metric |
| **manim-trainer / RITL** (arXiv 2604.18364, 2026) | Renderer-in-the-loop bounded retry with error feedback = our exact pattern | Qwen3-Coder-30B+GRPO+RITL-DOC: **94% render success / 85.7% visual sim** (vs 66% baseline) |
| **makefinks/manim-generator** (GitHub) | Code Writer + Code Reviewer loop; execution logs fed back; default 5 cycles; per-scene timeouts; **vision review of rendered frames** | model-agnostic (LiteLLM); public leaderboard manim-bench.makefinks.dev |

**Cheap, proven reliability levers we don't yet use:**
- **Truncate the error log to the last ~10 lines** in the repair prompt — sufficient to localize the failure (RITL).
- **RITL-DOC: retrieve relevant Manim API docs** into the repair prompt — biggest help for smaller/cheaper models.
- **VLM visual critic** on a rendered frame — render success ≠ visual quality; layout defects dominate residual errors (both TheoremExplainAgent & Code2Video).
- **Planning as its own stage** before codegen.

## SQ2 — Style representation (how to make it *actionable*)

- **Concrete demonstrations > abstract descriptors.** Adjectives ("friendly",
  "informative") are interpreted inconsistently; **2–3 examples** establish a
  reliable template, **1 risks being an outlier**, and positive+negative
  examples help. Example fidelity scales with example similarity.
- **Register-grounded descriptors** (arXiv 2505.00679): analyze an exemplar
  with Biber's register framework → comma-separated style adjectives → "rewrite
  to be more [descriptors]". Zero-shot, no fine-tune; **2.4–2.5× better meaning
  preservation** than open-ended descriptor extraction (STYLL).
  ⚠️ *Refuted overreach:* it is **not** proven "more accurate than
  unconstrained" — the accuracy claim is the authors' hypothesis with mixed
  results. Treat it as a *meaning-preservation* win, not a magic bullet.
- **SynDec** (arXiv 2505.12821): auto-synthesize prompts via 4-dimension style
  analysis + representative few-shot + reranking; beats SOTA on 5/6 benchmarks.
  No fine-tuning. → structured multi-dim analysis + representative exemplars.
- ⚠️ **Diminishing returns on elaborate machinery.** ZeroStylus (arXiv
  2505.07888) modular templates + retrieval only **marginally** beat a direct
  prompt (6.90 vs 6.70). Lesson: structured spec + exemplars is enough; don't
  build a retrieval-template cathedral.
- **3b1b's style is the *easy* case.** "Catch Me If You Can?" (arXiv
  2509.14543, EMNLP 2025): LLMs imitate **structured/formal** styles well
  (news/email) but **fail at nuanced informal** styles (blogs/forums). 3b1b
  has consistent visual grammar + clear pedagogical structure → squarely in the
  tractable regime.

**Verdict:** simplest-yet-effective = **structured JSON spec + concrete
exemplars (real transcript snippets + named frames) + register-grounded
adjectives.** *Not* fine-tuning. Our current profile is mostly adjectives —
it needs real exemplars baked in.

## SQ3 — Closing the loop (conditioning generation)

- **Description-based generation** splits *content* from a *style-description
  prompt*; a single NL descriptor can drive prosody/style. Directly applicable:
  feed profile fields into each stage.
- **StratL / TSI:** a *structured deterministic* mapping (state → intent →
  prompt chunk, with graph transitions) **beats** giving the LLM a plain-text
  description of the strategy. → operationalize, don't describe.
- Concretely for us: profile.pedagogy → script intent sequence;
  profile.visual.palette/motion → template params; profile.audio.pace_wpm +
  pause_pattern → TTS rate + pauses.

## SQ4 — Pedagogical structure transfer

- **LessonPlanner** (arXiv 2408.01102, UIST 2024): encoding Gagné's Nine Events
  of Instruction as a CoT scaffold beat free-form prompting — overall
  **32.25 vs 26.33 (p=0.02)**, teaching strategies p=0.034, detail p=0.007.
  Mechanism: *programmatically insert named instructional events + definitions
  per section.* ⚠️ small N=12, text lesson plans (domain gap to video).
- **StratL** (intents↔prompt chunks, deterministic graph): field test elicited
  **2.6 vs 1.0** student-generated methods (p=.05).
- **Scaffolding-as-knowledge-graph (TSI)** beats plain-text theory description;
  ablating the structure caused sharp drops.
- **Plain prompting fails to control pedagogy** — instruction-tuned LLMs
  optimize *user satisfaction*, not learning (they reveal answers despite being
  told not to). → structure must be enforced, not requested.
- ⚠️ **Eval caution:** Socratic vs Narrative study — *user preference ≠
  learning* (only 39% agreement). Depth-over-breadth; over-long "list" answers
  cause false sense of knowing. Pedagogy score must measure *structure*, not
  "feels good."
- Strong math-solving ≠ good teaching — condition the script LLM for teaching.

**Verdict:** encode 3b1b pedagogy as an explicit **named scene-intent template**
(motivate-with-puzzle → build-intuition-geometrically → formalize) with a
reusable prompt chunk per intent. We already have an `intent` field — formalize
it into a fixed contract.

## SQ5 — Voice / prosody without cloning

- **Controllable-TTS taxonomy** (survey arXiv 2412.06602, EMNLP 2025): four
  control strategies — style tagging, reference-speech prompt, **natural-language
  descriptions**, instruction-guided. NL prompts control emotion/timbre/style
  **without speaker cloning**.
- **ElevenLabs v3 Audio Tags** (official): bracketed inline directives
  `[pause]`, `[whispers]`, `[excited]`, `[drawn out]`, `[rushed]`, `[slows
  down]` control prosody/pacing/tone from text — descriptor-driven, no clone.
  ⚠️ reliability is experimental: tags sometimes ignored or read aloud
  ("~1 in 6" in some reports). Validate output.
- **Higgs Audio v3** (OSS, ~4B, Qwen3-4B backbone): inline control tokens for
  20+ emotions/styles/prosody; faster than real-time (RTF 0.147 on H100).
  ⚠️ its *speaker identity* path is zero-shot **cloning** (needs ref audio) —
  use **only** its control tokens, never the speaker path. Kokoro/XTTS similar.
- **InstructTTSEval** (arXiv 2506.16381): NL-instruction TTS bench; 3 task types
  (acoustic-param / descriptive-style / role-play). ⚠️ Don't over-read the
  "systems perform poorly" claim — Gemini Flash scored **93.8%** on the
  descriptive-style task. Off-the-shelf prosody-by-description is *usable*, not
  perfect.

**Verdict:** stay on macOS `say` with **`-r {pace_wpm}`** + **`[[slnc N]]`**
pauses now (covers pace + "short pauses after key claims" for $0, no clone);
add an **ElevenLabs v3 audio-tag** branch when the key is present; Higgs/Kokoro
control-token path as the OSS upgrade. Locked rule "never clone source voice"
is fully compatible with all of these.

## SQ6 — Evaluation (what's reliable vs noise)

- **LLM-as-judge correlates strongly** with humans for style transfer
  (GPT-4-class **0.92 Pearson** for style accuracy vs BLEU's 0.24) — but is
  **highly model-dependent** (weak models ~0.16–0.20). Use a capable judge.
- **Cross-family judging is validated** — self-preference bias inflates scores
  5–15%. (Our reviewer already uses Gemini to judge Claude output. ✅ Keep it.)
- **Score orthogonal axes, never one aggregate:** style accuracy, content
  preservation, fluency. (Our rubric's 5 dims align.)
- **Do NOT use BLEU/BERTScore/BLEURT for content preservation** in style
  transfer — they reward verbatim and penalize legitimate style change;
  correlation collapses to ~0 on adversarial sets.
- **Rubric reliability boosters:** concrete **anchor examples per score level**;
  **G-Eval = force step-by-step reasoning before the numeric score**; target
  inter-rater κ>0.6 / α≈0.8; a **jury of diverse models** beats one judge.
- **VBench**: decompose video quality into 16 dimensions (incl.
  `appearance_style`, `temporal_style`, `overall_consistency`) using
  dimension-specific pipelines (**CLIP** for style, RAFT for motion) — not one
  generic judge.
- ⚠️ Code-level similarity (CodeBLEU/AST) correlates **weakly** with visual
  fidelity — don't gate on it.

**Verdict:** keep the Gemini judge; add G-Eval CoT + score anchors; add **one
cheap automated visual metric (CLIP cosine between a generated frame and source
frames)** for `appearance_style`; keep axes separate.

## SQ7 — Highest-leverage, simplest changes for *this* pipeline

Priority order (impact ÷ effort):

1. **Close the loop** — wire `extract_profile` output into script-writer,
   template driver, and narrator. *Biggest win, modest effort.*
2. **Enrich the Style Profile schema** with concrete exemplars (verbatim
   transcript snippets + named frame files) + register-grounded adjectives.
3. **Operationalize pedagogy** as a fixed named scene-intent template.
4. **Harden the Manim loop**: last-10-lines error context + Manim API-doc
   retrieval in the repair prompt.
5. **Add a VLM visual critic** (one frame per scene) — render≠visual quality.
6. **Upgrade the reviewer**: G-Eval CoT, score anchors, CLIP visual metric.
7. **No-clone TTS control**: `say -r`/`[[slnc]]` now; ElevenLabs v3 tags later.

### What the refuted claims tell us NOT to do
- Don't build elaborate retrieval/template style machinery (marginal gains).
- Don't oversell register analysis as accuracy magic (it's meaning-preservation).
- Don't assume off-the-shelf prosody-by-description either fails or is perfect.
- Don't trust render success as visual quality, or code similarity as style.
- Don't trust user-preference as a pedagogy signal.

---

## Key sources
- TheoremExplainAgent — arXiv 2502.19400 (ACL 2025)
- Code2Video — arXiv 2510.01174 (ICML 2026)
- Training/Agentic Manim (RITL/RITL-DOC) — arXiv 2604.18364 (2026)
- makefinks/manim-generator — github.com/makefinks/manim-generator
- Register-analysis style transfer — arXiv 2505.00679 (2025)
- SynDec — arXiv 2505.12821 (2025)
- ZeroStylus — arXiv 2505.07888 (2025)
- "Catch Me If You Can?" implicit-style imitation — arXiv 2509.14543 (EMNLP 2025)
- LessonPlanner (Gagné's Nine Events) — arXiv 2408.01102 (UIST 2024)
- Controllable Speech Synthesis survey — arXiv 2412.06602 (EMNLP 2025)
- InstructTTSEval — arXiv 2506.16381 (2025)
- ElevenLabs v3 Audio Tags — elevenlabs.io/blog/v3-audiotags
- Higgs Audio v3 — (OSS, Qwen3-4B backbone)
- VBench (16-dim video eval) — VBench project
