"""Sources stage of the video processor."""

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from .titles import _sanitize_filename


def is_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
        "youtu.be", "www.youtu.be",
    }


def _video_cache_dir(url: str, output_root: Path) -> Path:
    """Cache directory based on YouTube ID or URL hash."""
    import re, hashlib
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    vid = m.group(1) if m else hashlib.sha1(url.encode()).hexdigest()[:12]
    d = output_root / "_cache" / vid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _has_video_and_audio(path: Path) -> bool:
    """Reject incomplete yt-dlp fragments and silent video-only formats."""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "json", str(path),
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    try:
        streams = json.loads(result.stdout)["streams"]
    except (ValueError, KeyError, TypeError):
        return False
    kinds = {stream.get("codec_type") for stream in streams}
    return {"video", "audio"} <= kinds


def _complete_mp4s(directory: Path) -> list[Path]:
    return [path for path in directory.glob("*.mp4") if _has_video_and_audio(path)]


def download_video(url: str, output_dir: Path, cache_root: Path, fresh: bool = False) -> Path:
    """Download best quality video+audio as a single mp4 file."""
    import yt_dlp

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "_download" if fresh else _video_cache_dir(url, cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = _complete_mp4s(cache_dir)
    if existing:
        print(f"⏩  Using cached download → {existing[0].name}")
        return existing[0]
    template = str(cache_dir / "%(title)s.%(ext)s")

    ydl_opts = {
        "format": (
            "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
            "best[vcodec^=avc1][ext=mp4]/best"
        ),
        "outtmpl": template,
        "merge_output_format": "mp4",
        "quiet": False,
        "noplaylist": True,          # only download single video, not a playlist
        "writeinfojson": True,       # saves metadata alongside video
    }

    print(f"\n📥  Downloading: {url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp sanitises the filename — find the actual file
        safe_title = ydl.prepare_filename(info).replace(".webm", ".mp4").replace(".mkv", ".mp4")
        video_path = Path(safe_title)

    if not video_path.exists() or not _has_video_and_audio(video_path):
        # yt-dlp can leave a video-only fragment before merging the audio.
        candidates = _complete_mp4s(cache_dir)
        if not candidates:
            raise RuntimeError(
                "Download did not produce an MP4 with both video and audio. "
                "Check the yt-dlp output and retry the download."
            )
        video_path = candidates[0]

    # Rename to a sanitized filename so derived paths (trimmed, vertical, etc.)
    # don't inherit special characters that break ffmpeg or Windows paths.
    clean_stem  = _sanitize_filename(video_path.stem)
    clean_path  = video_path.with_name(clean_stem + ".mp4")
    if clean_path != video_path:
        video_path.rename(clean_path)
        print(f"    Renamed → {clean_path.name}")
        video_path = clean_path

    print(f"✅  Downloaded → {video_path.name}")
    return video_path
