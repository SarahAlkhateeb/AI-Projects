"""Phase-2 quality-fix generator: profile + v3 script -> synced final MP4.

WHY v3 exists (it is the desync/pace/voice fix, not new scope):
- v2 muxed one combined audio track over a concatenated video whose per-scene
  lengths did not match, so narration drifted and the tail was cut off; it also
  narrated at the raw extracted pace (too fast) with the robotic `say` voice.
- v3 keeps the SAME closed-loop guarantee (palette/timing/voice all from the
  profile) but fixes delivery:
    * pace is clamped calm at consumption (conditioning, cap 140 wpm),
    * narration is engine-agnostic (ElevenLabs when keyed, else `say`),
    * the assembler times each video clip to its own scene's narration, then
      concats — so audio and video cannot drift.

This module renders the silent per-scene videos (reusing the v2 driver/render
helpers — same template-constrained drivers), narrates with the new engine-
agnostic stage, assembles with the synced assembler, and runs the objective A/V
sync gate. Output name depends on the engine: with a key it writes
today_demo_v3.mp4; without one it writes today_demo_v3_PREVIEW.mp4 (proves the
SYNC fix using the free `say` voice as a stand-in).

Run from project root:
    uv run python -m learnmorph.generate_v3
"""

import json
import sys
from pathlib import Path

from learnmorph.assemble import assemble
from learnmorph.conditioning import condition
from learnmorph.eval_metrics import av_sync
from learnmorph.generate_v2 import render, write_driver
from learnmorph.narrate import narrate

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "outputs" / "profiles" / "WUvTyaaNkzM.json"
SCRIPT = ROOT / "outputs" / "scripts" / "completing_square_v3.json"
FINAL_KEYED = ROOT / "outputs" / "final" / "today_demo_v3.mp4"
FINAL_PREVIEW = ROOT / "outputs" / "final" / "today_demo_v3_PREVIEW.mp4"


def main() -> dict:
    params = condition(PROFILE)
    visual = params["visual"]
    script = json.loads(SCRIPT.read_text())

    # 1) Render silent per-scene videos from the same template-constrained
    #    drivers used by v2 (profile-driven palette + timing). write_driver
    #    picks AreaModel for the geometric beat, EquationTransform otherwise.
    scene_videos = [
        render(write_driver(i, s, visual), i) for i, s in enumerate(script["scenes"], start=1)
    ]

    # 2) Narrate PER SCENE (engine auto-selected; pace clamped calm; pauses from
    #    the profile). Returns measured per-scene durations for the assembler.
    spoken = narrate(SCRIPT, PROFILE, slug="completing_square_v3")
    print(f"narration engine = {spoken['engine']} (total {spoken['total_seconds']}s)")

    # 3) Assemble: fit each video to its scene's audio, mux per scene, concat.
    final_path = FINAL_KEYED if spoken["engine"] == "elevenlabs" else FINAL_PREVIEW
    result = assemble(scene_videos, spoken["scenes"], final_path)

    # 3b) Record a MANIFEST of the EXACT per-scene audio this build muxed.
    #     WHY: the v3 audio dir can hold BOTH engines' files (e.g. leftover `say`
    #     .aiff preview stand-ins next to the real ElevenLabs .mp3). Summing the
    #     whole directory double-counts mixed engines and produces a bogus
    #     "expected narration" total. The verifier must use ONLY the files this
    #     build actually used, so we persist them here for it to read back.
    manifest = {
        "engine": spoken["engine"],
        "final_video": str(final_path),
        "scenes": [
            {"id": s["id"], "audio": str(s["path"]), "duration": round(float(s["duration"]), 3)}
            for s in spoken["scenes"]
        ],
        "intended_narration_seconds": round(sum(float(s["duration"]) for s in spoken["scenes"]), 3),
    }
    manifest_path = final_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"manifest -> {manifest_path}")

    # 4) Objective A/V sync gate — this is what makes the desync bug fail loud.
    sync = av_sync(result["per_scene"], result["final_video"], result["final_audio"])

    print(f"final -> {result['path']}")
    print(f"final video={result['final_video']:.3f}s audio={result['final_audio']:.3f}s")
    print("per-scene sync deltas:")
    for s in result["per_scene"]:
        print(f"  {s['id']}: video={s['video_dur']}s audio={s['audio_dur']}s delta={s['delta']}s")
    print(
        f"A/V SYNC OK = {sync['ok']}  (max_scene_delta={sync['max_scene_delta']}s, final_delta={sync['final_delta']}s)"
    )
    if not sync["ok"]:
        for f in sync["failures"]:
            print(f"  FAIL: {f}")

    return {"engine": spoken["engine"], "result": result, "sync": sync}


if __name__ == "__main__":
    out = main()
    sys.exit(0 if out["sync"]["ok"] else 1)
