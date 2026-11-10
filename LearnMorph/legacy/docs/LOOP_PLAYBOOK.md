# LearnMorph Loop Playbook
### The plain-language guide to the project, the plan, and how to run the self-driving loop

*Written June 2026. No background needed — every term is explained.*

---

## 1. What is LearnMorph? (explain it to anyone)

Some teachers are so good that people binge their videos. **3Blue1Brown** is a
famous example: beautiful animated math videos with a calm voice that always
starts with a puzzle, builds a picture in your head, and only *then* shows the
formula.

**LearnMorph watches one of those videos and learns *how* the teacher
teaches** — the colors, the motion, the calm pacing, the puzzle-first habit —
and writes it all down in a small, readable file called the **Style Profile**
(think: a recipe card for a teaching style).

Then you give it **any new topic**, and it cooks a brand-new short video *in
that same style*, using the recipe card. The style transfers; the topic is new.

**Important rule:** we never copy the teacher's actual *voice*. We match the
*feel* (calm, warm, ~140 words per minute) using a stock synthetic voice.
Copying a real person's voice without permission is off-limits, always.

---

## 2. How the machine works, step by step (and why each step is the best choice)

The pipeline is an assembly line. Each station does one job:

| # | Station | What it does | Why this way is best |
|---|---------|--------------|----------------------|
| 1 | **Download** | Grabs the source video | Simple, already proven. |
| 2 | **Transcribe** (Whisper) | Turns the speech into text with timing | Free, local, accurate — and the timings let us *measure* the teacher's real speaking pace instead of guessing it. |
| 3 | **Frames** (PySceneDetect) | Picks ~12–20 representative pictures from the video | Cheaper and more reliable than analyzing every frame; scene cuts are where the visuals change. |
| 4 | **Describe** (Gemini vision) | Writes down what's in each picture — colors, layout, motion | A vision model turns pixels into words the next step can reason about. |
| 5 | **Fuse → Style Profile** (Claude) | Merges the transcript + picture notes into the recipe card | One model that sees *both* what was said and what was shown produces one coherent profile. |
| 6 | **Conditioning** | Reads the recipe card and hands each later station its settings | **This is the heart.** Research shows a style file that just *describes* a style does nothing — it must *drive* the machine. This step is why our output changed from yellow-on-navy (hardcoded) to cyan-on-black (what the source video actually uses). |
| 7 | **Script writer** (Claude) | Writes the narration, one scene at a time | Each scene gets its own small instruction from a fixed teaching checklist (see below) — small scoped jobs beat one big vague job. |
| 8 | **Narrator** (ElevenLabs → `say` fallback) | Turns the script into a calm spoken voice | Natural stock voice, pace capped at ~140 wpm. Never voice cloning. |
| 9 | **Animator** (Manim templates) | Renders the animation | We only fill in **pre-built templates** (colors, equations, timing) — never let the AI write free-form animation code, which fails 30–50% of the time. If a render errors, the machine retries up to 3 times, showing itself only the *last few lines* of the error (proven to fix things faster). |
| 10 | **Assembler** (ffmpeg) | Stretches each scene's video to exactly match its audio, then glues scenes together | This is what fixed the "voice faster than the images" bug: sync per scene *first*, then join. A built-in checker now fails the build if audio and video drift more than 0.15s. |
| 11 | **Reviewer** (Gemini judge) | Scores the finished video 0–50 on five axes | A *different* company's model does the grading (models grade their own family too kindly — a documented bias). It must explain its reasoning *before* giving numbers. |

**The teaching checklist (why the videos "feel like" the teacher):**
instead of telling the AI "be like 3Blue1Brown" (a vibe it will ignore), the
Style Profile stores the teacher's actual habit as an ordered list —
`puzzle → build intuition with a picture → formalize` — and the script writer
is *forced* to write one scene per list item. Studies show this
checklist-not-vibe approach measurably beats free-form prompting.

---

## 3. What is "loop engineering"?

Prompt engineering is deciding *what to say* to an AI once.
**Loop engineering is designing the machine *around* the AI** that decides:

- what to work on next,
- whether the result is actually good,
- whether to retry, move on, stop, or ask a human.

Our loop uses the four patterns the field has converged on:

1. **Orchestrator + workers** *(Anthropic's pattern)* — one coordinator agent
   (`pipeline-runner`) reads the current task and delegates to specialist
   agents (script-writer, narrator, manim-writer, ffmpeg-assembler, reviewer).
   Several agents, each doing the one thing it's good at.
2. **Evaluator-optimizer** *(Anthropic's pattern)* — every attempt gets scored
   by the reviewer; the feedback goes into the *next* attempt. Generate →
   grade → improve → repeat.
3. **Fresh-start iterations with files as memory** *(the "Ralph loop" idea)* —
   each loop round launches a **fresh** agent with a clean head. All memory
   lives in files on disk: the plan (`ROADMAP.md`), the current task
   (`briefs/active.md`), and the scoreboard (`.learnmorph/last_status`).
   Fresh context every round prevents the confusion that builds up in long
   sessions; the files carry the state across rounds.
4. **Smart stopping** *(research: fixed iteration caps waste money and cut off
   progress)* — the loop stops on *signals*, not just counters:
   - **Quality reached** → score ≥ 35/50 → advance to the next phase.
   - **Plateau** → two rounds with almost no improvement → stop iterating,
     keep the best version so far ("best-so-far": we always ship the best
     attempt, never merely the latest).
   - **Budget** → hard caps: $5 per phase, $15 total. Money circuit-breaker.
   - **Blocked** → a human is needed (e.g. an API key) → pause politely and
     say exactly what's needed.

**The one thing research says matters most:** a loop is only as good as its
*feedback gates* — the automatic checks that catch bad work before it
compounds. Ours are: `ruff` (code style), `verify_dod` (18 objective checks,
including the audio/video sync gate that caught the v2 bug), and the
cross-family reviewer score.

---

## 4. Who are the agents in the loop?

| Agent | Job (one line) |
|---|---|
| `pipeline-runner` | The foreman. Reads the current task, delegates, verifies, decides advance/retry/stop, writes the scoreboard. |
| `script-writer` | Writes the narration script from the Style Profile. |
| `narrator` | Turns the script into audio (ElevenLabs George; `say` as backup). |
| `manim-writer` | Builds and renders the animations from templates. |
| `ffmpeg-assembler` | Syncs and glues scenes into the final MP4. |
| `reviewer` | Independent judge (Gemini) that scores the result 0–50. |

---

## 5. Where the project stands right now (June 2026)

- ✅ **Phase 1 — done.** First proof-of-concept video.
- ✅ **Phase 2 — done.** The Style Profile is now **extracted automatically**
  from the source video and **drives everything** (colors, pacing, teaching
  order). Final artifact: `outputs/final/today_demo_v3.mp4` — natural voice,
  calm pace, perfect sync. All 18 objective checks pass.
- ⬜ **Phase 3 — next.** Grow from 2 animation templates to 15+, add a
  safety-net template (so unknown topics never crash), build the
  "matchmaker" that picks the right template per scene, harden rendering.
- ⬜ **Phase 4 — last.** One command runs everything
  (`learnmorph run --source-url … --target-topic …`), with a daily rate limit
  and cost cap. Final proof: **2 different source styles × 3 new topics**,
  all convincing.

The loop's job is to drive Phases 3 → 4 to done.

---

## 6. HOW TO ACTIVATE THE LOOP — step by step

> **TL;DR:** open Terminal, `cd` into the project, run `./loop.sh`, watch.

### Step 0 — One-time pre-flight (2 minutes)

Open Terminal and paste, line by line:

```bash
cd <project-root>

# 1. All dependencies installed?
uv sync --extra dev --extra tts

# 2. Keys present? (should print three [SET] lines; ELEVENLABS may be unset — that's OK)
grep -E '^(ANTHROPIC|GOOGLE|ELEVENLABS)_API_KEY=' .env | sed 's/=.*/=[SET]/'

# 3. Claude Code logged in? (the loop uses your login, not the API key)
claude --version
```

If any of those fail, fix that first (the error will say what's missing).

### Step 1 — Start the loop

```bash
./loop.sh
```

That's it. Each round, the script launches a fresh coordinator agent that:
reads the current task → delegates to the specialists → runs the objective
checks → gets a reviewer score → decides **advance / retry / stop** → writes
the scoreboard file → exits. The script reads the scoreboard and either loops
again or stops.

### Step 2 — Watch progress (optional, second Terminal tab)

```bash
tail -f outputs/loop.log
```

You'll see lines like:
`Phase 3 iter 1 → status=RETRY, score=31 (best=31), this=$0.42, total=$1.13`

### Step 3 — Understand how it ends

The loop always ends in exactly one of three ways:

| Exit | Meaning | What you do |
|---|---|---|
| ✅ **COMPLETE** | All phases done; best final videos are in `outputs/` | Watch them. Celebrate. |
| ⏸ **BLOCKED** | It needs something only a human has (a key, a decision) | The log's last lines say exactly what. Provide it, run `./loop.sh` again — it resumes where it left off. |
| ❌ **FAILED** | Quality never reached the bar, or the money cap was hit | The log says which phase/why, and where the **best attempt so far** is saved. Nothing is lost. |

### Step 4 — Controls and safety rails (optional)

```bash
# Give it more/fewer rounds (default 20):
LEARNMORPH_MAX_ITERATIONS=8 ./loop.sh

# Change the total budget circuit-breaker (default $15):
LEARNMORPH_MAX_COST_USD=10 ./loop.sh

# Panic button — stop right now:
#   press Ctrl+C in the loop's Terminal window.
# It's always safe: all state lives in files, so the next ./loop.sh resumes cleanly.
```

**Built-in rails you don't need to configure:** $5 max per phase; max 3
attempts per phase; plateau detection; best-so-far always kept; the locked
rules (template-only animation, no voice cloning) apply to every agent.

### If the loop gets BLOCKED — the two likely asks

1. **Gemini daily quota** (free tier): the describe/review steps allow ~20
   calls/day. Fix: wait for the daily reset (~midnight Pacific) and rerun, or
   enable billing on the Google key.
2. **ElevenLabs monthly quota** (free tier: 10,000 characters). Our clips are
   tiny (~450 chars each), so this is unlikely — but if hit, the narrator
   automatically falls back to `say`, and the loop continues (premium voice
   can be re-rendered later).

---

## 7. Sources (the ideas behind this loop)

- Anthropic — [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
  (evaluator-optimizer & orchestrator-workers patterns)
- The "Ralph" autonomous-loop pattern — [what Ralph is](https://knightli.com/en/2026/04/27/ralph-autonomous-agent-loop-claude-code-amp/),
  [reference implementation](https://github.com/snarktank/ralph)
- [Loop Engineering: the guide for AI agents](https://lushbinary.com/blog/loop-engineering-ai-coding-agents-guide/)
  (feedback-gate quality is what makes loops work)
- [Semantic early-stopping for iterative agent loops](https://arxiv.org/pdf/2606.27009)
  (stop on plateau, not on a fixed counter)
- Style-transfer technique research for this project: `docs/RESEARCH_2026-06.md`
  (61 adversarially-verified findings with citations)
