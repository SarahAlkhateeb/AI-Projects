# LearnMorph — video stage brief (Claude Code)

Copy `learnmorph_video.py`, `remotion/`, and (when it lands) `learnmorph_avatar.py` into the LearnMorph project root (the folder with `pyproject.toml`, `data/`, `runs/`). Then:

## 0. Prereqs
```
uv add anthropic yt-dlp
brew install ffmpeg node          # if missing
cd remotion && npm install && cd ..
npx skills add remotion-dev/skills   # teaches you Remotion; restart the session after
```

## 1. Smoke-test Remotion with the bundled demo storyboard (no LLM calls)
```
cd remotion
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 1 public/audio/silence.mp3
npx remotion render src/index.ts Lesson out/demo.mp4
```
Open `out/demo.mp4`. Expect: yellow callout → e^x curve drawing with tangent → equation morphing. Fix any TS/runtime errors in `src/` before going further. The Remotion skill knows the API; use it.

## 2. Run the video stage on the existing text run
```
uv run learnmorph_video.py --run demo1 --teacher 3b1b \
  --source-video "https://www.youtube.com/watch?v=WUvTyaaNkzM" --stop-after storyboard
```
Show me `runs/demo1/profiles/3b1b/visual.json` and `runs/demo1/storyboards/3b1b.json`. Then drop `--stop-after` for the full render. Repeat for `--teacher lecturer` (Khan video URL from data/lecturer metadata).

## 3. Rules
- Never write animation code per lesson. The LLM fills template props (JSON); only `remotion/src/templates/` holds animation code. New template needed → add it there AND to `TEMPLATES` in `learnmorph_video.py`.
- Never clone the source teacher's voice or likeness. Neutral TTS / stock avatar only.
- Every stage is produce → judge → retry (max 3). Don't bypass a gate; if it keeps failing, report which rubric item fails and stop.
- `runs/demo1/log.md` is the record. Attempts are kept, nothing is overwritten.

## 4. Done when
Two MP4s in `runs/demo1/video/`, same topic, visibly different style, and `*_frame_scores_r*.json` show every beat passing.
