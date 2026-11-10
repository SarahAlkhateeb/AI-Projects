# Changelog

## 2026-11-10 (follow-up commits)
- Evaluation (`eval/`): recipe-free tests against real teachers. Generated text picked as human 0/40; unstyled
  control labelled 3b1b 20/20 (so the 3b1b result is uninformative); lecturer 20/20 attribution is real signal.
  The earlier 10/10 blind test measured recipe-following. Details in `docs/STATUS.md`.
- Chart templates: `bar_chart`, `line_chart`, `compare_split`, `stat_reveal` plus storyboard prompt
  sentences. tsc passes; no real Remotion render yet.
- Narration: sentence-level TTS is the default (`--mode phrase` keeps the old way; chatterbox engine added, not run).
  Little effect, since most phrases were already sentences. These files were already in the baseline commit.
- Housekeeping: demo2 plans, scripts and validation report added; `run_v2.command` no longer calls
  `learnmorph_video.py true`.

Reconstructed from file timestamps, `runs/*/log.md` (times only, no dates; dates below come from file
modification times) and `legacy/ROADMAP.md`. Anything uncertain is marked.

## 2026-11-08 to 2026-11-10 (v2 video stage)
- Several render and QA passes for demo1 (3b1b and lecturer) logged in `runs/demo1/log.md`, then demo2
  (3b1b, phrase-shot storyboard, 74 shots) in `runs/demo2/log.md`. Exact dates per entry are not recorded.
- `learnmorph_video.py` last modified 2026-11-08; `remotion/src/Lesson.tsx` 2026-11-08.
- 2026-11-10: `tts_vm.py` and `*_timed_phrase.json` storyboards updated (sentence vs phrase TTS modes).

## 2026-11-05 (v2 pipeline set up)
- `learnmorph.py`, `learnmorph_video.py` (v3 phrase-shot design per its docstring), `learnmorph_avatar.py`,
  `CLAUDE.md`, `BRIEF_claude_code.md` and `AVATAR_NOTES.md` carry this date.
- HeyGen API notes marked "verified 2026-11-05" in `AVATAR_NOTES.md`.

## 2026-11-08 (earlier) text-stage run
- `runs/demo1/validation/report.json` dated 2026-11-08: blind test 10/10. The demo1 log shows grammar,
  exemplar, plan, beat and assemble stages with scores (lecturer grammar gate failed, best kept).

## 2026-07-05
- `legacy/briefs/archive/2026-07-05_phase_2.md` and `legacy/docs/LOOP_PLAYBOOK.md` dated this day (v1 phase 2 work). Uncertain what shipped.

## 2026-06-28
- `legacy/ROADMAP.md` (4-phase plan), `legacy/docs/RESEARCH_2026-06.md` and `PLAN_REVISION_2026-06.md` written.

## 2026-06-07
- v1 Phase 1 (validation prototype) marked DONE in `legacy/ROADMAP.md`: `today_demo.mp4` produced (352 KB).
