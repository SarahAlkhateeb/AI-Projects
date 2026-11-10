"""Step 1 — Download a YouTube video as an MP4 file.

Why yt-dlp instead of the YouTube API:
- The YouTube Data API returns metadata only, not the actual video bytes.
- yt-dlp is the actively maintained successor to youtube-dl and handles
  every weird YouTube case (age-restricted, region-locked, format quirks).

Why MP4 specifically:
- ffmpeg can read MP4 natively (later steps).
- Whisper expects audio it can find inside an MP4 or WAV.
- It's the most portable format if we ever need to debug by hand.

Why we cap at 720p:
- We don't need 4K source video to extract style.
- Smaller files = faster everything downstream (less disk, less RAM).
"""

from pathlib import Path

import yt_dlp


def download_video(
    url: str,
    output_dir: Path = Path("outputs/videos"),
    max_height: int = 720,
) -> dict:
    """Download a YouTube video and return info about the saved file.

    Parameters
    ----------
    url : str
        A YouTube URL — e.g. "https://www.youtube.com/watch?v=aircAruvnKk"
    output_dir : Path
        Where to save the file. Created if it doesn't exist.
    max_height : int
        Cap the resolution. 720p is plenty for style extraction.

    Returns
    -------
    dict with keys:
        path     -> Path to the saved MP4 file
        title    -> Video title (str)
        duration -> Duration in seconds (int)
        id       -> YouTube video ID (str)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # yt-dlp's format string syntax — read as:
    # "best mp4 that's <=720p, OR any mp4, OR whatever is best"
    # Each / is a fallback.
    options = {
        "format": f"best[height<={max_height}][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "quiet": False,  # show progress in the notebook
        "noplaylist": True,  # if a playlist URL is passed, just take one video
        "merge_output_format": "mp4",
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    video_path = output_dir / f"{info['id']}.{info['ext']}"

    return {
        "path": video_path,
        "title": info.get("title", "unknown"),
        "duration": info.get("duration", 0),
        "id": info["id"],
    }
