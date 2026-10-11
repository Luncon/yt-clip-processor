"""Media stage of the video processor."""

import subprocess
import json
from pathlib import Path


def trim_video(video_path: Path, output_dir: Path, start: str = None, end: str = None) -> Path:
    """
    Trim video to a specific start/end time using ffmpeg.
    Accepts HH:MM:SS or plain seconds (e.g. "60", "00:01:00").
    Returns path to the trimmed file.
    """
    trimmed_path = output_dir / (video_path.stem + "_trimmed.mp4")

    if trimmed_path.exists():
        print(f"\u23e9  Trimmed video already exists \u279c {trimmed_path.name}")
        return trimmed_path

    label = f"{start or 'start'} \u2192 {end or 'end'}"
    print(f"\n\u2702\ufe0f   Trimming video: {label}")

    # When -ss is before -i (fast seek), -to is relative to the seek point.
    # So we convert start+end into a duration (-t) to be explicit and reliable.
    def _to_seconds(t):
        if t is None:
            return None
        if ":" in str(t):
            parts = str(t).split(":")
            parts = [float(p) for p in parts]
            if len(parts) == 3:
                return parts[0]*3600 + parts[1]*60 + parts[2]
            elif len(parts) == 2:
                return parts[0]*60 + parts[1]
        return float(t)

    start_s    = _to_seconds(start) or 0.0
    end_s      = _to_seconds(end)
    duration_s = (end_s - start_s) if end_s is not None else None

    if duration_s is not None and duration_s <= 0:
        raise ValueError(
            f"Invalid trim range: start ({start} = {start_s:.1f}s) is at or after "
            f"end ({end} = {end_s:.1f}s). Did you swap --start and --end?"
        )

    # Use fast seek (-ss before -i) + stream copy for near-instant trimming.
    # Slight keyframe imprecision (~1-2s) at the trim point is acceptable here
    # since the hook clips themselves are re-encoded for frame accuracy later.
    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", str(start_s)]
    cmd += ["-i", str(video_path)]
    if duration_s is not None:
        cmd += ["-t", str(duration_s)]
    cmd += [
        "-c", "copy",
        "-movflags", "+faststart",
        str(trimmed_path),
    ]

    _run_ffmpeg(cmd, quiet=True)
    print(f"\u2705  Trimmed \u279c {trimmed_path.name}  ({label})")
    return trimmed_path


def _extract_audio(video_path: Path, output_dir: Path) -> Path:
    """
    Extract audio track from video to a 16kHz mono WAV file.
    Whisper works on audio, not video — passing audio directly is significantly
    faster than letting faster-whisper decode the video stream itself.
    """
    wav_path = output_dir / (video_path.stem + "_audio.wav")
    if wav_path.exists():
        print(f"    \u23e9  Audio already extracted \u279c {wav_path.name}")
        return wav_path

    print(f"    \U0001f3b5  Extracting audio for transcription...")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                      # no video
        "-ar", "16000",             # 16 kHz — Whisper's native sample rate
        "-ac", "1",                 # mono
        "-c:a", "pcm_s16le",        # uncompressed WAV
        str(wav_path),
    ]
    _run_ffmpeg(cmd, quiet=True)
    print(f"    \u2705  Audio extracted \u279c {wav_path.name}")
    return wav_path


def _get_audio_duration(audio_path: Path) -> float:
    """Get duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"    ⚠️  ffprobe failed on {audio_path.name}:\n{out.stderr.strip()}")
        raise subprocess.CalledProcessError(out.returncode, cmd, output=out.stdout, stderr=out.stderr)
    return float(out.stdout.strip())


def _get_video_codec(video_path: Path) -> str:
    """Use ffprobe to detect the video codec name."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-print_format", "json",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        info = json.loads(result.stdout)
        return info["streams"][0]["codec_name"].lower()
    except Exception:
        return "unknown"




def _get_duration(video_path: Path) -> float:
    """Use ffprobe to get video duration in seconds."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def _run_ffmpeg(cmd: list, quiet: bool = False):
    """Run an ffmpeg command, streaming output or suppressing it."""
    if quiet:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    ⚠️  ffmpeg error:\n{result.stderr[-500:]}")
            raise subprocess.CalledProcessError(result.returncode, cmd)
    else:
        # Stream ffmpeg output so user can see progress
        with subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        ) as process:
            for line in process.stderr:
                # Only print progress lines to avoid spam
                if "time=" in line or "Error" in line or "error" in line.lower():
                    print(f"    {line.rstrip()}")
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd)
