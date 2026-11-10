#!/usr/bin/env bash
# Loop engineering driver — Evaluator-Optimizer inner + Plan-Execute-Reflect outer.
#
# Pipeline-runner writes .learnmorph/last_status after each iteration.
# This script reads it, decides whether to keep looping, exits on terminal state.
#
# Patterns:
#   - Anthropic Evaluator-Optimizer: https://www.anthropic.com/research/building-effective-agents
#   - Claude Code Auto mode (permission-mode auto): https://www.anthropic.com/engineering/claude-code-auto-mode
#
# Future: when Phase 4 lands, migrate this to the Agent SDK
# (https://code.claude.com/docs/en/agent-sdk/agent-loop) which gives us
# native max_turns / max_total_input_tokens / cost tracking instead of
# bash budget enforcement.
#
# Exit codes:
#   0 = COMPLETE (all phases done, best_artifact emitted)
#   1 = FAILED   (quality threshold missed after max iters, or budget exhausted)
#   2 = BLOCKED  (human input required — see log for what)

set -e
cd "$(dirname "$0")"

export PATH="$HOME/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Claude Code uses its OWN login session, not ANTHROPIC_API_KEY. Unset to
# avoid env-var collision — the Python pipeline still reads .env via load_dotenv().
unset ANTHROPIC_API_KEY

MAX_ITERATIONS="${LEARNMORPH_MAX_ITERATIONS:-20}"
MAX_COST_USD="${LEARNMORPH_MAX_COST_USD:-15.00}"
MAX_COST_PER_PHASE_USD="${LEARNMORPH_MAX_COST_PER_PHASE_USD:-5.00}"
STATE_DIR=".learnmorph"
STATUS_FILE="$STATE_DIR/last_status"
LOG_FILE="outputs/loop.log"
CLAUDE_OUTPUT_FILE="$STATE_DIR/last_claude_output"

mkdir -p "$STATE_DIR" "outputs"

status_get() {
  grep -E "^$1=" "$STATUS_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

diagnose_claude_failure() {
  local txt
  txt=$(cat "$CLAUDE_OUTPUT_FILE" 2>/dev/null || echo "")

  if echo "$txt" | grep -qiE "401|invalid authentication|unauthorized|not authenticated|failed to authenticate"; then
    echo "BLOCKED|claude_login|Claude Code is not authenticated. Run: claude login (then re-run ./loop.sh)."
    return
  fi
  if echo "$txt" | grep -qiE "rate limit|429|too many requests"; then
    echo "BLOCKED|rate_limit|Claude API is rate-limiting. Wait a few minutes and re-run ./loop.sh."
    return
  fi
  if echo "$txt" | grep -qiE "model.*not found|invalid model|model_not_found"; then
    echo "FAILED|bad_model|A subagent is requesting a model that doesn't exist. Check the model pin in your agent configs."
    return
  fi
  # Auto mode's safety classifier can refuse irreversible/destructive operations.
  # If you hit this, look at the output for which op was blocked and either
  # widen the subagent's allowed-tools list or restructure to avoid the destructive op.
  if echo "$txt" | grep -qiE "auto mode.*(blocked|refused)|safety classifier"; then
    echo "FAILED|auto_mode_blocked|Auto mode's safety classifier blocked an operation. See $CLAUDE_OUTPUT_FILE for which op was refused."
    return
  fi
  if echo "$txt" | grep -qiE "permission|requires approval|denied"; then
    echo "FAILED|permissions|Tool call denied — verify --permission-mode auto is being passed."
    return
  fi
  if echo "$txt" | grep -qiE "command not found.*claude|claude: not found"; then
    echo "BLOCKED|claude_missing|The 'claude' CLI is not on PATH. Install Claude Code or open your shell PATH."
    return
  fi
  if echo "$txt" | grep -qiE "network|connection refused|getaddrinfo|enotfound"; then
    echo "BLOCKED|network|Network failure reaching Claude. Check internet, then re-run ./loop.sh."
    return
  fi
  echo "FAILED|unknown|claude exited non-zero with no recognized pattern. See $CLAUDE_OUTPUT_FILE for details."
}

iteration=0
cumulative_cost=0

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }

log "=== Loop start (max=$MAX_ITERATIONS iter total, \$$MAX_COST_USD cumulative, \$$MAX_COST_PER_PHASE_USD per phase) ==="

while [ "$iteration" -lt "$MAX_ITERATIONS" ]; do
  iteration=$((iteration + 1))
  log "─── Driver iteration $iteration ───"

  # --permission-mode auto: official 2026 replacement for --dangerously-skip-permissions.
  #   Routes tool calls through a safety classifier that blocks irreversible/destructive
  #   ops while auto-approving safe ones. See https://code.claude.com/docs/en/auto-mode-config
  # --verbose: streams reasoning + tool calls inline (so the user sees thinking live).
  # | tee:    displays output AND captures it for diagnosis.
  # PIPESTATUS[0]: claude's exit code, not tee's.
  set +e
  claude --permission-mode auto --verbose -p "Use the pipeline-runner subagent in LOOP MODE to execute briefs/active.md. Follow the Evaluator-Optimizer protocol in your agent prompt: pre-flight human-input check, execute, verify objective Definition of done, call the reviewer subagent for subjective quality, apply best-so-far + plateau detection, then decide ADVANCED / COMPLETE / RETRY / FAILED / BLOCKED. Write the full status file at $STATUS_FILE before returning." 2>&1 | tee "$CLAUDE_OUTPUT_FILE"
  CLAUDE_EXIT=${PIPESTATUS[0]}
  set -e

  if [ $CLAUDE_EXIT -ne 0 ]; then
    DIAGNOSIS=$(diagnose_claude_failure)
    DIAG_STATUS=$(echo "$DIAGNOSIS" | cut -d'|' -f1)
    DIAG_CODE=$(echo "$DIAGNOSIS" | cut -d'|' -f2)
    DIAG_MSG=$(echo "$DIAGNOSIS" | cut -d'|' -f3)

    log "✗ claude exited $CLAUDE_EXIT. Diagnosis: $DIAG_CODE"
    log "  $DIAG_MSG"
    log "  Full output saved to $CLAUDE_OUTPUT_FILE"

    [ "$DIAG_STATUS" = "BLOCKED" ] && exit 2 || exit 1
  fi

  if [ ! -f "$STATUS_FILE" ]; then
    log "✗ Pipeline-runner did not write $STATUS_FILE. Aborting."
    log "  Possible cause: Auto mode blocked an operation, or pipeline-runner errored mid-task."
    log "  Check the output above for refused ops or unhandled exceptions."
    exit 1
  fi

  STATUS=$(status_get status)
  PHASE=$(status_get phase)
  ITER_IN_PHASE=$(status_get iteration)
  TOTAL_SCORE=$(status_get total_score)
  BEST_SCORE=$(status_get best_score)
  BEST_ARTIFACT=$(status_get best_artifact)
  COST_THIS=$(status_get cost_usd_this_iteration)
  COST_PHASE=$(status_get cost_usd_this_phase)
  cumulative_cost=$(status_get cumulative_cost_usd)
  DETAILS=$(status_get details)

  log "Phase $PHASE iter $ITER_IN_PHASE → status=$STATUS, score=$TOTAL_SCORE (best=$BEST_SCORE), this=\$$COST_THIS, phase=\$$COST_PHASE, total=\$$cumulative_cost"
  [ -n "$BEST_ARTIFACT" ] && log "  best_artifact=$BEST_ARTIFACT"
  [ -n "$DETAILS" ] && log "  $DETAILS"

  case "$STATUS" in
    ADVANCED) log "  → Phase $PHASE complete. Best score=$BEST_SCORE. Continuing." ;;
    RETRY)    log "  ↻ Retrying phase $PHASE (iter $ITER_IN_PHASE failed gate or below threshold)." ;;
    COMPLETE) log "✓ All phases complete. Best artifact: $BEST_ARTIFACT" ; exit 0 ;;
    FAILED)
      log "✗ Phase $PHASE FAILED: $DETAILS"
      log "  Best artifact for this phase: $BEST_ARTIFACT (score=$BEST_SCORE)"
      exit 1 ;;
    BLOCKED)
      HUMAN=$(status_get human_input_needed)
      log "⏸ BLOCKED — human input needed: $HUMAN"
      log "   Provide what's needed, then re-run ./loop.sh"
      exit 2 ;;
    *)        log "✗ Unknown status '$STATUS'. Aborting." ; exit 1 ;;
  esac

  if awk -v c="$cumulative_cost" -v cap="$MAX_COST_USD" 'BEGIN{exit !(c+0 > cap+0)}'; then
    log "✗ Cumulative cost cap exceeded (\$$cumulative_cost > \$$MAX_COST_USD). Aborting."
    exit 1
  fi
done

log "✗ Max driver iterations ($MAX_ITERATIONS) reached without completion. Aborting."
exit 1
