"""
LearnMorph video stage v3: beats → visual profile → phrase-shot storyboard → per-phrase TTS → Remotion → QA.

v3 architecture: the storyboard LLM splits each beat's narration into PHRASES (3-8s of speech) and gives each
phrase one shot (template + props). TTS then synthesizes each phrase separately; each clip's measured duration
IS the shot duration, so picture and voice are in sync by construction — no forced alignment, no whisper.

Stages are separable because this project runs across two sandboxes:
  --stop-after storyboard   : needs the Anthropic API (run where the API is reachable)
  tts_vm.py                 : needs only kokoro-onnx + ffmpeg (run where pypi/github are reachable)
  --render-only             : needs node + the remotion install (run on the Mac itself)

TTS engine (in tts_vm.py): ElevenLabs if key+credits, else kokoro-onnx (KOKORO_ONNX_MODEL/KOKORO_ONNX_VOICES
point at kokoro-v1.0.onnx and voices-v1.0.bin from github.com/thewh1teagle/kokoro-onnx releases), else macOS say.
"""

import argparse
import base64
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REMOTION = HERE / "remotion"
WRITER = os.getenv("LM_WRITER_MODEL", "claude-sonnet-5-5")
JUDGE = os.getenv("LM_JUDGE_MODEL", "claude-sonnet-5-5")

TEMPLATES = {
    "title_card":      {"title": "str", "subtitle": "str?"},
    "equation":        {"tex": "str", "highlight": "str? substring to colour"},
    "equation_morph":  {"from_tex": "str", "to_tex": "str", "highlight": "str?"},
    "plot":            {"fn": "js expr in x e.g. 'Math.exp(x)'", "x_range": "[a,b]", "y_range": "[a,b]", "label": "str?",
                        "point_at": "number?", "tangent_at": "number?", "bars_at": "[numbers]?",
                        "draw": "bool? first shot of a plot scene only"},
    "callout":         {"text": "str ≤ 12 words", "emphasis": "str?"},
    "number_line":     {"values": "[numbers]", "labels": "[str]", "highlight_index": "int?"},
    "bullet_build":    {"items": "[str] 2-4, ≤ 8 words each"},
    "misconception":   {"claim": "str", "correction": "str"},
    "diagram_nodes":   {"nodes": "[{id,label}]", "edges": "[{from,to,label?}]", "highlight": "id?"},
    "whiteboard_write": {"lines": "[str] 1-3"},
    "bar_chart":       {"bars": "[{label,value}] ≤ 24", "y_min": "number? truncates the axis (draws an axis break when > 0)",
                        "y_max": "number?", "highlight_index": "int?", "title": "str?", "unit": "str? e.g. '%'",
                        "show_values": "bool? default true"},
    "line_chart":      {"points": "[{x,y}] ≤ 400 (or series: [{name,points}] ≤ 6)", "x_labels": "[str]? ≤ 12",
                        "y_min": "number?", "y_max": "number?", "highlight_range": "[x0,x1]? shaded window", "title": "str?"},
    "compare_split":   {"left": "{title, chart}", "right": "{title, chart}",
                        "verdict": "str? ≤ 8 words; chart = bar_chart or line_chart props object"},
    "stat_reveal":     {"value": "number", "unit": "str?", "caption": "str ≤ 12 words", "from": "number? count-up start, default 0"},
}


# ---------------------------------------------------------------- helpers
def llm(system, user, model=WRITER, temperature=0.5, images=None, max_tokens=8000):
    """Raw Messages API via urllib — works wherever api.anthropic.com is reachable, no SDK needed."""
    import urllib.error
    import urllib.request
    key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY not set")
    content = [{"type": "text", "text": user}]
    for p in images or []:
        content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                       "data": base64.b64encode(Path(p).read_bytes()).decode()}})
    payload = {"model": model, "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": content}]}
    if temperature is not None:
        payload["temperature"] = temperature
    for attempt in range(4):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode(),
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            return "".join(b["text"] for b in data["content"] if b["type"] == "text")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            if e.code == 400 and "temperature" in msg and "temperature" in payload:
                del payload["temperature"]; continue
            if e.code in (400, 401, 403, 404):
                raise RuntimeError(f"API {e.code}: {msg}")
            if attempt == 3:
                raise RuntimeError(f"API {e.code} after retries: {msg}")
            time.sleep(3 * 2 ** attempt)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(3 * 2 ** attempt)


def llm_json(system, user, **kw):
    txt = llm(system + "\nRespond with valid JSON only, no fences.", user, **kw)
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M)
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        fixed = llm("Return ONLY this content as valid JSON. Fix syntax, change nothing else.", txt, temperature=0)
        return json.loads(re.sub(r"^```(?:json)?|```$", "", fixed.strip(), flags=re.M))


def sh(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"{cmd}\n{p.stderr[-2000:]}")
    return p.stdout


def _native_prefix():
    """Rosetta guard for node.

    uv's CPython here is x86_64, so subprocesses it spawns inherit that slice.
    Node then reports arch=x64 and Remotion looks for
    @remotion/compositor-darwin-x64, while npm (run natively) installed the
    arm64 build. Re-exec node natively when that mismatch is actually present.
    """
    if sys.platform != "darwin" or platform.machine() != "x86_64":
        return ""
    r = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True)
    return "arch -arm64 " if r.stdout.strip() == "1" else ""


NATIVE = _native_prefix()


def _unstringify(v):
    """Parse props the writer emitted as JSON *strings* back into real values.

    Models intermittently return '[0,1]' instead of [0,1]. A string survives
    .length and [0] indexing, so a template either dies on .map or silently
    scales by NaN and draws nothing — the second is much worse to debug.
    """
    if isinstance(v, str):
        t = v.strip()
        if t[:1] in "[{" and t[-1:] in "]}":
            try:
                return json.loads(t)
            except ValueError:
                return v
    return v


def _fix_props(storyboard):
    """Coerce every shot's props in place; returns how many were repaired."""
    n = 0
    for b in storyboard.get("beats", []):
        for holder in [b, *b.get("shots", [])]:
            props = holder.get("props")
            if not isinstance(props, dict):
                continue
            for k, v in props.items():
                fixed = _unstringify(v)
                if fixed is not v:
                    props[k] = fixed
                    n += 1
    return n


def log(run, msg):
    line = f"- {time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(run / "log.md", "a") as f:
        f.write(line + "\n")


def loop(run, name, produce, evaluate, max_rounds, out_path):
    if out_path.exists():
        log(run, f"[{name}] cached"); return json.loads(out_path.read_text())
    fb, best, best_s = None, None, -1
    for r in range(1, max_rounds + 1):
        out = produce(fb)
        ev = evaluate(out)
        log(run, f"[{name}] r{r} score={ev['score']:.2f} pass={ev['pass']} — {ev['feedback'][:110]}")
        if ev["score"] > best_s:
            best, best_s = out, ev["score"]
        if ev["pass"]:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(out, indent=2)); return out
        fb = ev["feedback"]
    log(run, f"[{name}] gate failed; keeping best {best_s:.2f}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(best, indent=2)); return best


# ---------------------------------------------------------------- V1: visual profile
def stage_visual_profile(run, teacher, source, max_rounds):
    out = run / "profiles" / teacher / "visual.json"
    frames_dir = run / "profiles" / teacher / "frames"
    frames = sorted(frames_dir.glob("*.jpg")) if frames_dir.exists() else []
    if not frames and source and not out.exists():
        frames_dir.mkdir(parents=True, exist_ok=True)
        try:
            vid = source
            if source.startswith("http"):
                vid = str(frames_dir / "src.mp4")
                sh(f'yt-dlp --no-update --js-runtimes node -f "bv*[height<=480]/bv*" -o "{vid}" "{source}"')
            sh(f'ffmpeg -y -i "{vid}" -vf "fps=1/20,scale=640:-1" -frames:v 12 "{frames_dir}/f_%02d.jpg"')
        except RuntimeError:
            log(run, f"[visual:{teacher}] reference video unavailable; inferring without frames")
        frames = sorted(frames_dir.glob("*.jpg"))

    def produce(fb):
        fbtxt = f"\nFix from reviewer:\n{fb}\n" if fb else ""
        return llm_json(
            "You extract a VISUAL STYLE PROFILE from reference frames of a teacher's videos. Hex colours, named "
            "motions, numbers. If no frames, infer from the teacher's well-known style and say so in 'confidence'." + fbtxt,
            f"Teacher: {teacher}\nTemplates: {list(TEMPLATES)}\n"
            'Return {"palette":{"bg":"#..","fg":"#..","accent":"#..","accent2":"#..","muted":"#.."},'
            '"font":{"family":"css font-family string","math":"serif|sans"},'
            '"motion":{"speed":"slow|medium|fast","easing":"ease|spring|linear","camera":"none|drift|push",'
            '"shot_seconds":[min,max],"signature":"one line"},'
            '"layout":"one line","output_format":"animation|whiteboard|avatar","format_reason":"one line",'
            '"template_affinity":{template: 0-1},"confidence":"high|medium|low"}',
            images=[str(f) for f in frames[:8]], temperature=0.2)

    def evaluate(prof):
        ev = llm_json("Audit a visual style profile. Strict but fair: hex codes, a css font, numeric shot_seconds "
                      "and a named camera move count as specific.",
                      f"{json.dumps(prof)}\nScore 1-5: specificity; consistency; usability. "
                      'Return {"scores":{...},"feedback":"..."}', model=JUDGE, temperature=0)
        s = ev["scores"]; avg = sum(s.values()) / len(s)
        return {"score": avg, "pass": avg >= 3.7, "feedback": ev["feedback"]}

    prof = loop(run, f"visual:{teacher}", produce, evaluate, max_rounds, out)
    prof.setdefault("motion", {}).setdefault("shot_seconds", [3, 8])
    prof["motion"].setdefault("camera", "drift")
    return prof


# ---------------------------------------------------------------- V2: phrase-shot storyboard
def stage_storyboard(run, teacher, beats, visual, max_rounds):
    out = run / "storyboards" / f"{teacher}.json"
    smin, smax = visual["motion"]["shot_seconds"]
    wmin, wmax = int(smin * 2.3), int(smax * 2.6)  # ~2.4 words/sec speech

    def produce(fb):
        fbtxt = f"\nFix from reviewer:\n{fb}\n" if fb else ""
        beats_out = []
        for b in beats:
            sb = llm_json(
                "You are a motion designer. Split ONE beat of narration into PHRASES and give each phrase one SHOT. "
                f"A phrase is {wmin}-{wmax} words of the narration, split at natural pauses (sentence or clause "
                "boundaries). The phrases concatenated must be the narration VERBATIM — same words, same order, "
                "nothing added or dropped. Each shot SHOWS what its phrase says: a number spoken appears on screen; "
                "'slide to x=2' moves the dot. Consecutive shots using a scene template (plot, diagram_nodes, "
                "number_line) share one scene — same fn/x_range/nodes, change only point_at/highlight/bars_at. "
                "bar_chart, line_chart and compare_split are scene templates too (keep the same bars/points, change only "
                "y_min/highlight): use them for any bar or data-series chart, never plot; stat_reveal for one big number. "
                "'draw': true only on the first shot of a plot scene. On-screen text ≤ 12 words, never a transcript. "
                "Rhythm: open on a scene, cut to an equation/callout for the key line, return to the scene." + fbtxt,
                f"Templates and prop schemas:\n{json.dumps(TEMPLATES)}\nVisual profile:\n{json.dumps(visual)}\n"
                f"Beat type: {b['beat']}\nNarration:\n{b['text']}\n"
                'Return {"shots":[{"phrase":"verbatim narration slice","template":name,"props":{...},"why":"≤8 words"}]}',
                temperature=0.4)
            beats_out.append({"i": b["i"], "beat": b["beat"], "narration": b["text"], "shots": sb["shots"]})
        return {"teacher": teacher, "beats": beats_out}

    def evaluate(sb):
        problems = []
        for b in sb["beats"]:
            joined = re.sub(r"\s+", " ", " ".join(s["phrase"] for s in b["shots"])).strip().lower()
            orig = re.sub(r"\s+", " ", b["narration"]).strip().lower()
            # token-level comparison, forgiving about punctuation
            tj = re.findall(r"[a-z0-9']+", joined); to = re.findall(r"[a-z0-9']+", orig)
            if tj != to:
                problems.append(f"beat {b['i']}: phrases are not the narration verbatim")
            for s in b["shots"]:
                if s["template"] not in TEMPLATES:
                    problems.append(f"beat {b['i']}: unknown template {s['template']}")
                w = len(s["phrase"].split())
                if w > wmax * 1.5:
                    problems.append(f"beat {b['i']}: phrase of {w} words too long")
        ev = llm_json("Audit a shot storyboard. Strict on: does each shot SHOW what its phrase says (not decorate)? "
                      "Scene continuity kept? On-screen text short and not a transcript?",
                      f"Storyboard:\n{json.dumps(sb)[:60000]}\nScore 1-5: phrase_match, continuity, text_discipline. "
                      'Return {"scores":{...},"feedback":"per-beat issues, concrete"}', model=JUDGE, temperature=0)
        s = ev["scores"]; avg = sum(s.values()) / len(s)
        fb = ev["feedback"] + (" STRUCTURAL: " + "; ".join(problems[:8]) if problems else "")
        return {"score": avg - 0.7 * len(problems), "pass": avg >= 3.8 and not problems, "feedback": fb}

    return loop(run, f"storyboard:{teacher}", produce, evaluate, max_rounds, out)


# ---------------------------------------------------------------- V3: render + QA (needs timed storyboard from tts_vm.py)
def still_runs(mp4, threshold=4.0):
    txt = subprocess.run(f'ffmpeg -i "{mp4}" -vf "freezedetect=n=0.003:d={threshold}" -map 0:v -f null -',
                         shell=True, capture_output=True, text=True).stderr
    starts = [float(m) for m in re.findall(r"freeze_start: ([\d.]+)", txt)]
    durs = [float(m) for m in re.findall(r"freeze_duration: ([\d.]+)", txt)]
    return list(zip(starts, durs))


def stage_render(run, teacher, visual, max_rounds, judge=True):
    timed = run / "storyboards" / f"{teacher}_timed.json"
    if not timed.exists():
        sys.exit(f"Missing {timed}; run tts_vm.py first")
    storyboard = json.loads(timed.read_text())
    fixed = _fix_props(storyboard)
    if fixed:
        log(run, f"[render:{teacher}] repaired {fixed} JSON-stringified props")
    fps = 30
    payload = {"teacher": teacher, "fps": fps, "theme": visual, "beats": storyboard["beats"]}
    # Absolute: the render runs with cwd=remotion/, so a relative path lands in
    # remotion/runs/... and the project-root ffmpeg calls then can't find it.
    out_mp4 = (run / "video" / f"{teacher}.mp4").resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if not (REMOTION / "node_modules").exists():
        sh(f"{NATIVE}npm install", cwd=REMOTION)
    for rnd in range(1, max_rounds + 1):
        (REMOTION / "public" / "storyboard.json").write_text(json.dumps(payload, indent=2))
        chrome = os.getenv("LM_CHROME")
        flag = f' --browser-executable="{chrome}"' if chrome else ""
        sh(f'{NATIVE}npx remotion render src/index.ts Lesson "{out_mp4}" --log=error' + flag, cwd=REMOTION)
        stills = still_runs(out_mp4)
        log(run, f"[render:{teacher}] r{rnd} rendered; still runs ≥4s: {len(stills)}")
        if not judge:
            return out_mp4
        frames_dir = run / "video" / f"{teacher}_frames"; frames_dir.mkdir(exist_ok=True)
        t0, checks = 0.0, []
        for b in storyboard["beats"]:
            for k, s in enumerate(b["shots"]):
                mid = t0 + (s["start_s"] + s["end_s"]) / 2
                fp = frames_dir / f"b{b['i']}_s{k}.jpg"
                sh(f'ffmpeg -y -ss {mid:.2f} -i "{out_mp4}" -frames:v 1 -vf scale=800:-1 "{fp}"')
                ev = llm_json("Judge ONE frame of an explainer video against the phrase being spoken.",
                              f"Phrase: {s['phrase']}\nShot: {json.dumps({k: s[k] for k in ('template', 'props')})}\n"
                              f"Palette/layout: {json.dumps({k: visual[k] for k in ('palette', 'layout')})}\n"
                              "Score 1-5: legible; shows_the_phrase; on_style. "
                              'Return {"scores":{...},"fix":"prop change, or empty"}', images=[str(fp)], model=JUDGE, temperature=0)
                sc = ev["scores"]; checks.append({"beat": b["i"], "shot": k, "avg": sum(sc.values()) / 3, "min": min(sc.values()), "fix": ev["fix"]})
            t0 += b["duration_s"]
        failing = [c for c in checks if c["avg"] < 3.7 or c["min"] < 3]
        (run / "video" / f"{teacher}_qa_r{rnd}.json").write_text(json.dumps({"stills": stills, "shots": checks}, indent=2))
        log(run, f"[render:{teacher}] r{rnd} shots pass {len(checks)-len(failing)}/{len(checks)}")
        if not failing and not stills:
            return out_mp4
        for c in failing:
            b = next(x for x in storyboard["beats"] if x["i"] == c["beat"]); s = b["shots"][c["shot"]]
            new = llm_json("Revise ONLY props to fix the note. Keep the template.",
                           f"Shot: {json.dumps(s)}\nSchema: {json.dumps(TEMPLATES[s['template']])}\nNote: {c['fix']}\nReturn {{\"props\":{{...}}}}", temperature=0.3)
            s["props"] = new["props"]
        if stills:
            visual["motion"]["camera"] = "push"
        payload["theme"] = visual; payload["beats"] = storyboard["beats"]
        timed.write_text(json.dumps(storyboard, indent=2))
    log(run, f"[render:{teacher}] max rounds; video at {out_mp4} with remaining issues")
    return out_mp4


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--teacher", required=True)
    ap.add_argument("--source-video", default=None)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--stop-after", choices=["visual", "storyboard"], default=None)
    ap.add_argument("--render-only", action="store_true", help="render from <teacher>_timed.json (after tts_vm.py)")
    ap.add_argument("--no-judge", action="store_true", help="with --render-only: skip the vision QA loop")
    a = ap.parse_args()
    run = Path("runs") / a.run
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not on PATH")
    visual_f = run / "profiles" / a.teacher / "visual.json"

    if a.render_only:
        visual = json.loads(visual_f.read_text())
        visual.setdefault("motion", {}).setdefault("shot_seconds", [3, 8]); visual["motion"].setdefault("camera", "drift")
        mp4 = stage_render(run, a.teacher, visual, a.max_rounds, judge=not a.no_judge)
        log(run, f"done → {mp4}")
        return

    beats_f = run / "scripts" / f"{a.teacher}_beats.json"
    if not beats_f.exists():
        sys.exit(f"Missing {beats_f}; run learnmorph.py first")
    beats = json.loads(beats_f.read_text())
    visual = stage_visual_profile(run, a.teacher, a.source_video, a.max_rounds)
    if a.stop_after == "visual":
        return
    stage_storyboard(run, a.teacher, beats, visual, a.max_rounds)
    log(run, f"storyboard done → next: tts_vm.py --run {a.run} --teacher {a.teacher}, then --render-only")


if __name__ == "__main__":
    main()
