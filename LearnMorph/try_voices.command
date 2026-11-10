#!/bin/bash
# Voice trial: double-click. First run downloads PyTorch and the Chatterbox model (a few GB, several minutes).
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p runs/voice_trial
exec > >(tee runs/voice_trial/log.txt) 2>&1
echo "===== voice trial $(date) ====="
[ -f .env ] && set -a && . ./.env && set +a
uv run --no-project --python 3.11 --with chatterbox-tts try_voices.py
echo "===== DONE $(date) ====="
open runs/voice_trial
