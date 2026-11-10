# LearnMorph — Proposed Plan Revision (June 2026)

Derived from `docs/RESEARCH_2026-06.md`. Keeps the locked rules in `CLAUDE.md`
intact (template-constrained Manim, deterministic pipeline, no voice cloning,
single agentic render step). Changes are **additive and surgical** — the
research says *don't* build elaborate machinery; the wins are in wiring what we
already have and adding a few cheap, proven levers.

## The core problem this fixes

Today the Style Profile is **extracted but never consumed**. `script-writer`
hand-rolls style, the template **hardcodes** `#FFD166`/`#0E1116`, TTS pace is a
fixed `-r 145`. We have a moat artifact that doesn't drive anything. **Closing
that loop is the whole game.**

---

## Revised phases (deltas only)

### Phase 2 → "Auto Style Profile **+ Close the Loop**"  *(was: extract + regenerate)*

Already ~80% coded and now unblocked (Gemini quota reset). Add:

1. **Enrich the Profile schema** (the artifact must be *actionable*, not just
   descriptive):
   - `visual.palette` {background, primary, accent} — already present.
   - `visual.motion_vocabulary` — map to concrete Manim animation names.
   - `audio.pace_wpm` (measured, already grounded) + `audio.pause_pattern`.
   - **NEW `exemplars`**: 2–3 *verbatim transcript snippets* + named frame files
     (concrete demonstrations >> adjectives — verified).
   - **NEW `style_descriptors`**: comma-separated register-grounded adjectives
     (Biber-style) produced in the fusion step.
   - **NEW `pedagogy.intent_sequence`**: ordered named intents
     (`motivate-with-puzzle` → `build-intuition-geometrically` → `formalize`).
2. **Wire the profile into generation** (`learnmorph/conditioning.py`, one small
   module that reads a profile and emits per-stage params):
   - `script-writer` prompt ← `style_descriptors` + `exemplars` (few-shot) +
     `intent_sequence` ("write to be more [descriptors]").
   - template driver ← `palette` + `motion_vocabulary` (stop hardcoding colors).
   - `narrator` ← `pace_wpm` → `say -r`, `pause_pattern` → `[[slnc N]]`.
3. **DoD (revised):** `today_demo_v2.mp4` is generated **entirely from the
   extracted profile** — zero hand-rolled style values. Profile validates against
   the enriched schema. Reviewer ≥ threshold.

### Phase 3 → "Template Library + **Render Reliability** + Premium Narration"

Keep the ≥15-template goal. Add the proven cheap reliability levers to the
render loop (`/render-scene` + `manim-writer`):

1. **Last-10-lines error context** in the repair prompt (RITL).
2. **Manim API-doc retrieval** into the repair prompt (RITL-DOC) — biggest help
   for cheaper models.
3. **VLM visual critic**: one Gemini-vision check on the first frame of each
   rendered scene vs the palette/layout spec (render success ≠ visual quality).
4. **Premium narration, no-clone:** ElevenLabs v3 **audio-tag** branch
   (`[pause]`, `[drawn out]`, descriptor-driven) when key present; `say`
   fallback otherwise (already the locked default). Higgs/Kokoro control-token
   path as the OSS option. *Never* the speaker-clone path.

### Cross-cutting → "Reviewer / Eval Upgrade"  *(can land now; benefits every phase)*

Upgrade the `reviewer` agent + `/quality-check`:
1. **G-Eval**: force step-by-step reasoning *before* the numeric score.
2. **Concrete score anchors** in the rubric (what a 3 / 6 / 9 looks like).
3. **One cheap automated visual metric**: CLIP cosine between a generated frame
   and source-style frames → `appearance_style`. Objective, not LLM-noise.
4. Keep cross-family Gemini judge (validated). Keep axes separate; never gate on
   a single aggregate or on code-similarity.

### Phase 4 → "Pipeline Orchestration (CLI)"  *(unchanged + one add)*

LangGraph DAG + CLI + rate-limit + cost cap + 3 demos, as specified. Add
**planning as its own node** before scene codegen (separate planning stage is
empirically essential for coherent multi-scene output).

---

## What we deliberately are NOT doing (research-backed)

- No fine-tuning (structured spec + exemplars is enough).
- No elaborate retrieval/template style engine (marginal gains over direct prompt).
- No voice cloning of any kind (locked; and descriptor control is sufficient).
- No gating on BLEU / code-similarity (poor correlation with real fidelity).
- No trusting render success or user-preference as quality signals.

## Suggested execution order

1. **Unblock + finish Phase 2 core** (extract real profile JSON — minutes away).
2. **Close the loop** (`conditioning.py` + wire 3 stages) → regenerate
   `today_demo_v2.mp4` from the profile. ← *highest leverage*
3. Land the **reviewer/eval upgrade** (cheap, helps everything downstream).
4. Phase 3 (templates + reliability levers + ElevenLabs branch).
5. Phase 4 (LangGraph CLI + 3 demos).
