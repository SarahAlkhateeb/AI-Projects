"""Stage — scene-cut detection + one representative frame per scene.

WHY scene-cut detection (not fixed-interval sampling):
- 3b1b videos hold a single visual idea on screen for a while, then cut to the
  next. Sampling every N seconds would oversample static holds and miss short
  but important transitions. Cutting on *content change* gives us one frame per
  distinct visual beat — exactly the granularity the describe/profile stages
  want.

WHY PySceneDetect ContentDetector at threshold ~27:
- ContentDetector compares frame-to-frame HSV change; ~27 is the library's
  well-tested default sweet spot for "real cut, not noise". We expose it as a
  parameter so it can be nudged per source.

WHY sample the MIDDLE frame of each scene:
- The first/last frames of a scene are often mid-transition (fades, wipes). The
  midpoint is the most representative "settled" frame of that beat.
"""

from pathlib import Path

import cv2
from scenedetect import ContentDetector, detect


def sample_frames(
    video_path: Path,
    output_dir: Path = Path("outputs/frames"),
    threshold: float = 27.0,
    max_frames: int = 12,
) -> dict:
    """Detect scene cuts and save one representative frame per scene.

    Parameters
    ----------
    video_path : Path
        Path to the source MP4.
    output_dir : Path
        Where to save the sampled JPG frames. A per-video subdir is created.
    threshold : float
        ContentDetector sensitivity. Lower = more cuts. ~27 is the default.
    max_frames : int
        Cap on frames saved, to keep the downstream Gemini bill bounded. Default
        12 leaves headroom under Gemini's free-tier per-day request cap (flash =
        20/day). If more scenes are detected, they're sampled evenly.

    Returns
    -------
    dict with keys:
        frame_paths -> list[Path] of saved JPG frames (in time order)
        scene_count -> number of scenes detected (int)
        frame_count -> number of frames actually saved (int)
        out_dir     -> Path to the per-video frame directory
    """
    video_path = Path(video_path)
    out_dir = Path(output_dir) / video_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # detect() returns a list of (start, end) FrameTimecode pairs.
    # WHY the try/except: scenedetect 0.7's OpenCV backend can raise
    # "cannot convert float NaN to integer" when seeking near EOF on some
    # MP4s (its timecode math hits a NaN pts). That must not kill the whole
    # extraction pipeline — a scene-cut read failure degrades gracefully to
    # evenly-spaced frame sampling, which still gives the describe/profile
    # stages a representative spread of visual beats.
    try:
        scene_list = detect(str(video_path), ContentDetector(threshold=threshold))
    except Exception:  # any decode/timecode failure -> even sampling
        scene_list = []

    # Fallback: if the detector finds no cuts (very short clip) OR it failed
    # above, sample evenly across the video so we still emit useful frames.
    if not scene_list:
        cap = cv2.VideoCapture(str(video_path))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        cap.release()
        # Evenly spaced interior frames (skip the very first/last, often blank
        # or mid-transition). Cap at max_frames to bound the Gemini bill.
        n = min(max_frames, max(1, total // 2))
        midpoints = [int(total * (k + 1) / (n + 1)) for k in range(n)]
        scene_count = n
    else:
        scene_count = len(scene_list)
        midpoints = []
        for start, end in scene_list:
            sf, ef = start.get_frames(), end.get_frames()
            midpoints.append((sf + ef) // 2)
        # Evenly subsample if we exceed the cap.
        if len(midpoints) > max_frames:
            step = len(midpoints) / max_frames
            midpoints = [midpoints[int(i * step)] for i in range(max_frames)]

    cap = cv2.VideoCapture(str(video_path))
    frame_paths: list[Path] = []
    for idx, frame_no in enumerate(midpoints):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            continue
        fp = out_dir / f"scene_{idx:02d}.jpg"
        cv2.imwrite(str(fp), frame)
        frame_paths.append(fp)
    cap.release()

    return {
        "frame_paths": frame_paths,
        "scene_count": scene_count,
        "frame_count": len(frame_paths),
        "out_dir": out_dir,
    }


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/videos/WUvTyaaNkzM.mp4")
    result = sample_frames(src)
    print(f"frames -> {result['out_dir']}")
    print(f"scenes={result['scene_count']} frames_saved={result['frame_count']}")
