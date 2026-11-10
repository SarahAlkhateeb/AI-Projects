# Avatar renderer: HeyGen notes (verified 2026-11-05)

Verified against docs.heygen.com/docs/create-video and /reference/create-an-avatar-video-v2:
- Auth header is `X-Api-Key`. Generate is `POST /v2/video/generate` → `data.video_id`.
- Poll with `GET /v1/video_status.get?video_id=…`. Status values are pending, processing, completed and failed. The file is at `data.video_url`, and that URL expires after 7 days.
- `video_inputs[].character` = {type:"avatar", avatar_id, avatar_style normal|circle|closeUp, scale, offset}; `voice` = {type:"text", input_text, voice_id, speed 0.5-1.5}; `background` = {type:"color", value:"#hex"} | image | video.
- Limits: the free plan exports at 720p at most, `input_text` must be under 1500 chars, and videos over 3600s fail (40119).
- List endpoints: `GET /v2/avatars` and `GET /v2/voices`.

Cost (HeyGen help centre "New HeyGen API plans", billed per second): Avatar III studio/stock avatar costs $0.99/min (20 credits). Avatar IV studio costs $4.83/min (97 credits). That works out to about $0.05 per credit. The docs don't say which engine `/v2/video/generate` uses for a stock avatar by default, so assume the Avatar IV rate until the first bill.

Not verified:
- The response schemas for `/v2/avatars` and `/v2/voices` weren't shown in the docs (field names `avatars[].avatar_id/avatar_name/premium` and `voices[].voice_id/language` are assumed). Passing `--avatar-id`/`--voice-id` explicitly avoids this.
- Whether a `normal` stock avatar is centred in frame. The PiP centre-crops a square from it.
- Whether `dimension` without `aspect_ratio` is accepted on paid plans.
