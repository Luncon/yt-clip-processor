"""Sources stage of the video processor."""

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


def download_video(url: str, output_dir: Path, cache_root: Path, fresh: bool = False) -> Path:
    """Download best quality video+audio as a single mp4 file."""
    import yt_dlp

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "_download" if fresh else _video_cache_dir(url, cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = list(cache_dir.glob("*.mp4"))
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

    if not video_path.exists():
        # Fallback: just grab the first mp4 in output_dir
        candidates = list(cache_dir.glob("*.mp4"))
        if not candidates:
            raise FileNotFoundError("Download seemed to succeed but no mp4 found.")
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
