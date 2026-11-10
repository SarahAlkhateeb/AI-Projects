# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic"]
# ///
"""
LearnMorph avatar renderer: storyboard → HeyGen presenter clip per beat → PiP over the Remotion render → vision judge.

For teachers whose visual profile has output_format == "avatar" (presenter-led, Khan-Academy-like).
Runs AFTER learnmorph_video.py has written runs/<id>/storyboards/<teacher>.json (narration + durations).

    uv run learnmorph_avatar.py --run demo1 --teacher lecturer [--avatar-id X] [--voice-id Y] [--max-rounds 3]

HARD RULE: the presenter is always a neutral STOCK HeyGen avatar + stock voice. Never clone, upload, or
imitate the source teacher's face or voice (no instant/digital-twin/photo avatars of them, no voice clones).
We transfer pedagogical style, not identity. Pass a stock --avatar-id / --voice-id; the auto-pick below only
looks at public avatars and refuses anything whose name contains the teacher's name.

Requires: HEYGEN_API_KEY, ANTHROPIC_API_KEY, ffmpeg/ffprobe, node 18+, remotion/ next to this file.
Clips are cached in runs/<id>/video/<teacher>_avatar/ so retries never re-bill HeyGen.
"""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from learnmorph_video import JUDGE, REMOTION, llm_json, log, loop, sh

# HeyGen REST API, verified 2026-11-05 against:
#   https://docs.heygen.com/docs/create-video                    (generate, status polling, X-Api-Key, 720p free plan)
#   https://docs.heygen.com/reference/create-an-avatar-video-v2  (character / voice / background fields)
#   https://docs.heygen.com/reference/list-avatars-v2, /list-voices-v2 (endpoints only; response schema not shown)
API = "https://api.heygen.com"
W, H, FPS = 1920, 1080, 30
DEFAULT_LAYOUT = {"size": 0.26, "corner": "br", "margin": 40}  # size = fraction of frame width (square PiP)
CORNERS = {"br": ("main_w-overlay_w-{m}", "main_h-overlay_h-{m}"), "bl": ("{m}", "main_h-overlay_h-{m}"),
           "tr": ("main_w-overlay_w-{m}", "{m}"), "tl": ("{m}", "{m}")}


# ---------------------------------------------------------------- HeyGen
def hg(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"], "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HeyGen {path} → {e.code}: {e.read().decode()[:500]}") from e
    if r.get("error"):
        raise RuntimeError(f"HeyGen {path} error: {r['error']}")
    return r["data"]


def pick_stock(teacher, avatar_id, voice_id):
    # Response shapes of list endpoints are NOT in the docs we could read; parsed defensively.
    if not avatar_id:
        avs = [a for a in hg("/v2/avatars").get("avatars", [])
               if a.get("avatar_id") and teacher.lower() not in str(a.get("avatar_name", "")).lower()
               and not a.get("premium")]
        if not avs:
            sys.exit("No stock avatar found; pass --avatar-id (a public HeyGen avatar, never a clone of the teacher)")
        avatar_id = avs[0]["avatar_id"]
    if not voice_id:
        vs = [v for v in hg("/v2/voices").get("voices", []) if v.get("voice_id")
              and str(v.get("language", "")).lower().startswith("english")]
        if not vs:
            sys.exit("No stock English voice found; pass --voice-id")
        voice_id = vs[0]["voice_id"]
    return avatar_id, voice_id


def avatar_clips(run, teacher, beats, avatar_id, voice_id, bg):
    d = run / "video" / f"{teacher}_avatar"; d.mkdir(parents=True, exist_ok=True)
    ids_f = d / "video_ids.json"
    ids = json.loads(ids_f.read_text()) if ids_f.exists() else {}
    for b in beats:  # submit everything first, poll after: HeyGen renders in parallel
        k = str(b["i"])
        if (d / f"beat_{k}.mp4").exists() or k in ids:
            continue
        if len(b["narration"]) >= 1500:
            sys.exit(f"beat {k}: narration >= 1500 chars (HeyGen limit); split the beat")
        ids[k] = hg("/v2/video/generate", {
            "title": f"learnmorph {run.name} {teacher} beat {k}",
            "dimension": {"width": 1280, "height": 720},  # free plan caps at 720p
            "video_inputs": [{
                "character": {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"},
                "voice": {"type": "text", "input_text": b["narration"], "voice_id": voice_id},
                "background": {"type": "color", "value": bg}}]})["video_id"]
        ids_f.write_text(json.dumps(ids, indent=2))
        log(run, f"[avatar:{teacher}] beat {k} submitted → {ids[k]}")
    deadline = time.time() + 30 * 60
    for b in beats:
        k, mp4 = str(b["i"]), d / f"beat_{b['i']}.mp4"
        while not mp4.exists():
            st = hg(f"/v1/video_status.get?video_id={ids[k]}")
            if st["status"] == "completed":
                urllib.request.urlretrieve(st["video_url"], mp4)  # URL expires in 7 days; we keep the file
            elif st["status"] == "failed":
                ids.pop(k); ids_f.write_text(json.dumps(ids, indent=2))
                raise RuntimeError(f"HeyGen beat {k} failed: {st.get('error')}")
            elif time.time() > deadline:
                raise TimeoutError(f"HeyGen beat {k} still {st['status']} after 30 min; rerun to resume")
            else:
                time.sleep(15)
        b["avatar_clip"] = str(mp4)
        b["avatar_s"] = float(sh(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{mp4}"').strip())
    log(run, f"[avatar:{teacher}] {len(beats)} clips ready, {sum(b['avatar_s'] for b in beats):.1f}s speech")
    return beats


# ---------------------------------------------------------------- base render + composite
def render_base(run, teacher, sb, theme):
    """Retime beats to the avatar's speech, then render the Remotion visuals once (their audio gets dropped)."""
    for b in sb["beats"]:
        b["duration_s"] = round(b["avatar_s"] + 0.4, 2)
    payload = {"teacher": teacher, "fps": FPS, "theme": theme, "beats": sb["beats"]}
    (run / "storyboards" / f"{teacher}_avatar.json").write_text(json.dumps(payload, indent=2))
    base = run / "video" / f"{teacher}_avatar_base.mp4"
    if not base.exists():
        (REMOTION / "public" / "storyboard.json").write_text(json.dumps(payload, indent=2))
        if not (REMOTION / "node_modules").exists():
            sh("npm install", cwd=REMOTION)
        sh(f'npx remotion render src/index.ts Lesson "{base.resolve()}" --log=error', cwd=REMOTION)
        log(run, f"[avatar:{teacher}] base render → {base}")
    t, spans = 0, []  # beat spans in seconds, from frame counts exactly as Root.tsx computes them
    for b in sb["beats"]:
        n = round(b["duration_s"] * FPS); spans.append((t / FPS, (t + n) / FPS)); t += n
    return base, spans


def composite(base, beats, spans, lay, out):
    w = int(W * lay["size"]) // 2 * 2
    x, y = (e.format(m=lay["margin"]) for e in CORNERS[lay["corner"]])
    ins = " ".join(f'-i "{b["avatar_clip"]}"' for b in beats)
    f, prev = [], "0:v"
    for k, (b, (a, z)) in enumerate(zip(beats, spans), start=1):
        f.append(f"[{k}:v]crop=ih:ih,scale={w}:{w},setpts=PTS-STARTPTS+{a:.3f}/TB[p{k}]")
        f.append(f"[{prev}][p{k}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{a:.3f},{z:.3f})'[o{k}]")
        f.append(f"[{k}:a]atrim=0:{z - a:.3f},apad=whole_dur={z - a:.3f}[a{k}]")
        prev = f"o{k}"
    f.append("".join(f"[a{k}]" for k in range(1, len(beats) + 1)) + f"concat=n={len(beats)}:v=0:a=1[aout]")
    graph = out.with_suffix(".filter.txt"); graph.write_text(";\n".join(f))
    # Remotion audio is muted by not mapping 0:a; only the avatar's voice is kept.
    sh(f'ffmpeg -y -i "{base}" {ins} -filter_complex_script "{graph}" -map "[{prev}]" -map "[aout]" '
       f'-c:v libx264 -pix_fmt yuv420p -crf 20 -c:a aac -b:a 160k -t {spans[-1][1]:.3f} "{out}"')


# ---------------------------------------------------------------- stage: avatar render + vision judge
def stage_avatar(run, teacher, sb, theme, avatar_id, voice_id, max_rounds):
    beats = avatar_clips(run, teacher, sb["beats"], avatar_id, voice_id, theme["palette"]["bg"])
    base, spans = render_base(run, teacher, sb, theme)
    out = run / "video" / f"{teacher}_avatar.mp4"
    frames_dir = run / "video" / f"{teacher}_avatar_frames"; frames_dir.mkdir(exist_ok=True)
    state = {"rnd": 0, "last": None}

    def produce(fb):
        if not fb:
            return dict(DEFAULT_LAYOUT)
        new = llm_json("You place a picture-in-picture presenter over lesson visuals. Change ONLY size, corner, "
                       "margin so the presenter never covers the text/equation/plot the narration is about.",
                       f"Current layout: {json.dumps(state['last'])}\nReviewer notes per beat:\n{fb}\n"
                       'Return {"size":0.15-0.35,"corner":"br|bl|tr|tl","margin":16-80}', temperature=0.2)
        return {"size": min(max(float(new["size"]), 0.15), 0.35),
                "corner": new["corner"] if new["corner"] in CORNERS else "br",
                "margin": int(min(max(new["margin"], 16), 80))}

    def evaluate(lay):
        state["rnd"] += 1; state["last"] = lay
        composite(base, beats, spans, lay, out)
        checks = []
        for b, (a, z) in zip(beats, spans):
            fp = frames_dir / f"beat_{b['i']}.jpg"
            sh(f'ffmpeg -y -ss {(a + z) / 2:.2f} -i "{out}" -frames:v 1 -vf scale=800:-1 "{fp}"')
            ev = llm_json(
                "You judge ONE frame of a presenter-led educational video: lesson visual full-frame, presenter "
                "picture-in-picture in a corner. Style and legibility only.",
                f"Beat: {json.dumps({k: b[k] for k in ('beat', 'template', 'props', 'narration')})}\n"
                f"Visual profile: {json.dumps(theme)}\nPresenter layout: {json.dumps(lay)}\n"
                "Score 1-5: legible (text/equations readable, nothing clipped OR hidden behind the presenter); "
                "matches_narration (the picture shows what is being said); on_style (palette/typography/feel). "
                'Return {"scores":{...},"fix":"how to move/resize the presenter, or empty"}',
                images=[str(fp)], model=JUDGE, temperature=0)
            s = ev["scores"]
            checks.append({"i": b["i"], "avg": sum(s.values()) / len(s), "min": min(s.values()), "fix": ev["fix"]})
        (run / "video" / f"{teacher}_avatar_frame_scores_r{state['rnd']}.json").write_text(json.dumps(checks, indent=2))
        failing = [c for c in checks if c["avg"] < 4 or c["min"] < 3]
        return {"score": sum(c["avg"] for c in checks) / len(checks) - len(failing) * 0.1, "pass": not failing,
                "feedback": f"{len(checks) - len(failing)}/{len(checks)} frames pass. "
                            + " ".join(f"beat {c['i']}: {c['fix']}" for c in failing)}

    lay = loop(run, f"avatar:{teacher}", produce, evaluate, max_rounds, run / "video" / f"{teacher}_avatar_layout.json")
    if lay != state["last"] or not out.exists():  # loop keeps the best round, which may not be the last one rendered
        composite(base, beats, spans, lay, out)
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--teacher", required=True)
    ap.add_argument("--avatar-id", default=None, help="stock HeyGen avatar_id (never a clone of the teacher)")
    ap.add_argument("--voice-id", default=None, help="stock HeyGen voice_id")
    ap.add_argument("--max-rounds", type=int, default=3)
    a = ap.parse_args()
    if not os.getenv("HEYGEN_API_KEY"):
        sys.exit("HEYGEN_API_KEY not set (HeyGen → Settings → API). Avatar rendering needs it.")
    for tool in ("ffmpeg", "ffprobe", "node", "npx"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not on PATH")
    run = Path("runs") / a.run
    sb_f, vis_f = run / "storyboards" / f"{a.teacher}.json", run / "profiles" / a.teacher / "visual.json"
    for f in (sb_f, vis_f):
        if not f.exists():
            sys.exit(f"Missing {f}; run learnmorph_video.py --stop-after tts first")
    sb, theme = json.loads(sb_f.read_text()), json.loads(vis_f.read_text())
    if theme.get("output_format") != "avatar":
        log(run, f"[avatar:{a.teacher}] warning: visual profile output_format={theme.get('output_format')!r}, not 'avatar'")
    if any("audio" not in b for b in sb["beats"]):
        sys.exit("Storyboard beats lack 'audio'; Remotion's Lesson needs it. Run the tts stage first.")
    avatar_id, voice_id = pick_stock(a.teacher, a.avatar_id, a.voice_id)
    log(run, f"[avatar:{a.teacher}] stock avatar={avatar_id} voice={voice_id}")
    mp4 = stage_avatar(run, a.teacher, sb, theme, avatar_id, voice_id, a.max_rounds)
    log(run, f"done → {mp4}")


if __name__ == "__main__":
    main()
