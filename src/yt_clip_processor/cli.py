"""Command-line interface for the video processor."""

import argparse
import importlib.util
import math
import shutil
import subprocess
from pathlib import Path

from .pipeline import run
from .source_selection import choose_monitored_source
from .sources import is_youtube_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download YouTube video → transcribe → burn subs → cut into clips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", nargs="?", help="YouTube video URL or local video file")
    parser.add_argument("--from-monitor", action="store_true",
                        help="Choose a rising recent video from saved source monitor data")
    parser.add_argument("--monitor-db", type=Path, default=Path("output/source-monitor.sqlite3"),
                        help="Source monitor database (default: output/source-monitor.sqlite3)")
    parser.add_argument(
        "--output", "-o", default="./output",
        help="Base output directory (default: ./output)",
    )
    parser.add_argument(
        "--clip-length", "-l", type=int, default=60,
        help="Length of each clip in seconds (default: 60)",
    )
    parser.add_argument(
        "--whisper-model", "-m",
        choices=["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v2", "large-v3"],
        default="base.en",
        help="Whisper model size (default: base.en). tiny/base are fastest, large-v3 is most accurate.",
    )
    parser.add_argument(
        "--no-burn-subs", action="store_true",
        help="Skip burning subtitles; just cut the original video into clips",
    )
    parser.add_argument(
        "--no-transcribe", action="store_true",
        help="Skip transcription entirely (no subtitles at all)",
    )
    parser.add_argument(
        "--no-vertical", action="store_true",
        help="Skip reframing to 9:16 vertical (keep original aspect ratio)",
    )
    parser.add_argument(
        "--words-per-line", "-w", type=int, default=5,
        help="Max words shown on screen at once (default: 5). Lower = more dynamic.",
    )
    parser.add_argument(
        "--subtitle-delay", "-d", type=float, default=0.2,
        help="Seconds to delay subtitles relative to audio (default: 0.2). Increase if subs appear too early.",
    )
    parser.add_argument(
        "--font", default=None,
        help=(
            "Font for subtitles. Can be a font name (e.g. 'Arial') or a path to a "
            ".ttf file (e.g. '/fonts/BebasNeue-Regular.ttf'). "
            "Defaults to a system font (Arial/Helvetica/DejaVu Sans)."
        ),
    )
    parser.add_argument(
        "--keep-original", action="store_true",
        help="Save a copy of the downloaded source under output/originals",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Download the source again instead of using the download cache",
    )
    parser.add_argument(
        "--start", default=None,
        help="Start time for trimming (e.g. 00:01:00 or 60). Useful for testing on a section.",
    )
    parser.add_argument(
        "--end", default=None,
        help="End time for trimming (e.g. 00:02:00 or 120).",
    )
    parser.add_argument(
        "--auto-clips", "--hooks", dest="hooks", type=int, default=0, metavar="N",
        help=(
            "Automatically select up to N complete, distinct clips. "
            "Replaces uniform cutting; --hooks is an older alias."
        ),
    )
    parser.add_argument(
        "--auto-clip-length", "--hook-clip-length", dest="hook_clip_length", type=int,
        metavar="SECONDS",
        default=60, help="Target automatic clip length in seconds (default: 60)",
    )
    parser.add_argument("--min-auto-score", type=int, default=65,
                        help="Minimum automatic selection score, 0-100 (default: 65)")
    parser.add_argument("--no-semantic-rank", action="store_true",
                        help="Use only local scoring even when GROQ_API_KEY is set")
    parser.add_argument(
        "--single", action="store_true",
        help="Only look for single-person scenes (disables dual/reaction detection). "
             "Combine with --dual/--reaction to allow more than one. Default: all three enabled.",
    )
    parser.add_argument(
        "--dual", action="store_true",
        help="Only look for dual-face (split-screen) scenes. "
             "Combine with --single/--reaction to allow more than one. Default: all three enabled.",
    )
    parser.add_argument(
        "--reaction", action="store_true",
        help="Only look for reaction-cam scenes (small corner face over separate content). "
             "Combine with --single/--dual to allow more than one. Default: all three enabled.",
    )
    parser.add_argument(
        "--no-llm-titles", action="store_true",
        help="Skip LLM-based clip titles even if GROQ_API_KEY is set; use the local "
             "leading-words heuristic instead.",
    )
    return parser


def parse_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    for name in ("clip_length", "hook_clip_length", "words_per_line"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.hooks < 0:
        parser.error("--auto-clips cannot be negative")
    if args.hooks and args.no_transcribe:
        parser.error("--auto-clips requires transcription")
    if not 0 <= args.min_auto_score <= 100:
        parser.error("--min-auto-score must be between 0 and 100")
    if args.from_monitor and (args.url or not args.hooks or args.start or args.end):
        parser.error("--from-monitor requires --auto-clips and no URL or trim range")
    if not args.from_monitor and not args.url:
        parser.error("provide a video URL or path, or use --from-monitor")
    if args.url and not Path(args.url).expanduser().is_file() and not is_youtube_url(args.url):
        parser.error("source must be an existing file or a YouTube video URL")
    try:
        start = _seconds(args.start) if args.start is not None else 0.0
        end = _seconds(args.end) if args.end is not None else None
    except ValueError:
        parser.error("--start and --end must be seconds or MM:SS or HH:MM:SS")
    if start < 0 or (end is not None and end <= start):
        parser.error("trim range must have a nonnegative start and end after start")
    args.source_decision = None
    return args


def _seconds(value: str) -> float:
    parts = value.split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(value)
    numbers = [float(part) for part in parts]
    if any(not math.isfinite(number) or number < 0 for number in numbers):
        raise ValueError(value)
    if len(numbers) > 1 and any(number >= 60 for number in numbers[1:]):
        raise ValueError(value)
    return sum(number * 60**index for index, number in enumerate(reversed(numbers)))


def check_dependencies(args):
    missing = []
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            missing.append(executable)
    local_source = Path(args.url).expanduser().is_file()
    packages = []
    if not local_source:
        packages.append(("yt_dlp", "yt-dlp"))
    needs_transcription = not args.no_transcribe or args.hooks
    if needs_transcription:
        packages.append(("faster_whisper", "faster-whisper"))
    if needs_transcription or not args.no_vertical:
        packages.append(("numpy", "numpy"))
    if not args.no_vertical:
        packages.extend((("mediapipe", "mediapipe"), ("cv2", "opencv-python")))
    for module, package in packages:
        if importlib.util.find_spec(module) is None:
            missing.append(package)
    if missing:
        raise RuntimeError("Missing dependencies: " + ", ".join(missing))


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.from_monitor:
            args.source_decision = choose_monitored_source(
                args.monitor_db, args.hook_clip_length, args.hooks)
            args.url = args.source_decision["url"]
            print(f"Selected {args.source_decision['source']}: "
                  f"{args.source_decision['reason']}")
            print(args.url)
        check_dependencies(args)
        run(args)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        build_parser().exit(1, f"error: {exc}\n")
