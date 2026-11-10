#!/bin/bash
# LearnMorph v2 runner. Double-click = repair remotion install + render both videos.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"  # /usr/local first: Thursday's render used this node
mkdir -p runs; exec > >(tee -a runs/v2_run.log) 2>&1
echo "===== $(date) stage=${1:-render} ====="; set -e
[ -f .env ] && set -a && . ./.env && set +a
STAGE=${1:-render}
echo "node=$(node -v) arch=$(uname -m) rosetta=$(sysctl -n sysctl.proc_translated 2>/dev/null)"
(cd remotion && npx remotion versions 2>&1 | head -6)
if [ "$STAGE" = render ]; then
  ( cd remotion
    npm install --no-audit --no-fund
    npx remotion browser ensure || true )
  uv run learnmorph_video.py true || (cd remotion && npx remotion render src/index.ts Lesson out/diag.mp4 --log=verbose 2>&1 | tail -60)
  uv run learnmorph_video.py --run demo2 --teacher lecturer --render-only
  echo; echo "VIDEOS:"; ls -la runs/demo1/video/*.mp4
fi
echo "===== DONE $(date) ====="
