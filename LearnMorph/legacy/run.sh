#!/usr/bin/env bash
# One-shot headless execution of briefs/active.md via the pipeline-runner subagent.

set -e
cd "$(dirname "$0")"

# Render toolchain on PATH (TinyTeX, ffmpeg, cairo).
export PATH="$HOME/Library/TinyTeX/bin/universal-darwin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Claude Code uses its OWN login session, not ANTHROPIC_API_KEY in .env.
unset ANTHROPIC_API_KEY

if [ ! -f briefs/active.md ]; then
  echo "briefs/active.md not found." >&2
  exit 1
fi

# --permission-mode auto: official 2026 headless flag (routes tool calls through
#   a safety classifier that blocks destructive ops). Replacement for the older
#   --dangerously-skip-permissions. https://code.claude.com/docs/en/auto-mode-config
# --verbose: streams reasoning + tool calls inline so progress is visible.
exec claude --permission-mode auto --verbose -p "Use the pipeline-runner subagent to execute briefs/active.md."
