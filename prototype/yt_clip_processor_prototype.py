#!/usr/bin/env python3
"""
YouTube Video Processor
-----------------------
Downloads a YouTube video, transcribes it with faster-whisper,
burns subtitles into the video, then cuts it into 1-minute clips.

Requirements (install first):
    pip install yt-dlp faster-whisper mediapipe opencv-python
    # Also needs ffmpeg installed on your system:
    # macOS:   brew install ffmpeg
    # Ubuntu:  sudo apt install ffmpeg
    # Windows: https://ffmpeg.org/download.html

Usage:
    python yt_clip_processor.py <YouTube URL> [options]

Examples:
    python yt_clip_processor.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    python yt_clip_processor.py "https://youtu.be/dQw4w9WgXcQ" --clip-length 90 --output ./my_clips
    python yt_clip_processor.py "https://youtu.be/..." --whisper-model medium --no-burn-subs
"""

import argparse
import os
import subprocess
import sys
import json
import shutil
import math
from pathlib import Path


# ─── Dependency checks ────────────────────────────────────────────────────────

def check_dependencies():
    missing = []
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg  →  brew install ffmpeg  /  sudo apt install ffmpeg")
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp  →  pip install yt-dlp")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        missing.append("faster-whisper  →  pip install faster-whisper")
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        missing.append("mediapipe  →  pip install mediapipe")
    if missing:
        print("❌  Missing dependencies:\n")
        for m in missing:
            print(f"    {m}")
        sys.exit(1)


# ─── Step 1: Download ─────────────────────────────────────────────────────────

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



def _sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are illegal or problematic in filenames
    on Windows, Linux, and inside ffmpeg shell arguments.
    Keeps the name human-readable; replaces runs of spaces/underscores.
    """
    import re
    # Characters illegal on Windows: \ / : * ? " < > |
    # Also strip curly quotes, fullwidth variants, and control chars
    name = name.replace("｜", "-")   # fullwidth pipe
    name = name.replace("|",  "-")   # regular pipe
    name = re.sub(r'[\\/:*?"<>]', "", name)   # Windows-illegal chars
    name = re.sub(r"['\u2018\u2019\u201c\u201d`]", "", name)  # quotes
    name = re.sub(r"[^\x20-\x7E]", "_", name)   # non-ASCII → underscore
    name = re.sub(r"[\s_]+", "_", name.strip())  # collapse whitespace/underscores
    name = name.strip("_.- ")        # trim leading/trailing junk
    return name or "video"           # never return empty string




def _video_cache_dir(url: str, output_root: Path) -> Path:
    """Cache directory based on YouTube ID or URL hash."""
    import re, hashlib
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    vid = m.group(1) if m else hashlib.sha1(url.encode()).hexdigest()[:12]
    d = output_root / "_cache" / vid
    d.mkdir(parents=True, exist_ok=True)
    return d
def download_video(url: str, output_dir: Path) -> Path:
    """Download best quality video+audio as a single mp4 file."""
    import yt_dlp

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = _video_cache_dir(url, output_dir.parent)
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
        candidates = list(output_dir.glob("*.mp4"))
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


# ─── Step 2: Transcribe with faster-whisper ──────────────────────────────────

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


CHUNK_SEC   = 15 * 60   # 15 min of audio per chunk — keeps peak memory bounded regardless
                        # of total video length, instead of loading the whole track at once
                        # (this is what was causing the OOM kill on long videos)
OVERLAP_SEC = 8         # extra audio fed to whisper on each side of a chunk boundary so it
                        # has surrounding context right at the cut (helps accuracy); words
                        # landing in the overlap are only kept from whichever chunk's CORE
                        # window they fall in, so nothing gets duplicated in the output


def _transcribe_words_chunked(audio_path: Path, model_name: str, output_dir: Path):
    """
    Transcribe a (potentially very long) audio file in fixed-size chunks instead
    of handing the whole file to faster-whisper at once. Peak memory is bounded
    by CHUNK_SEC of audio, not by total video length — a 3 hour podcast and a
    10 minute clip use roughly the same amount of RAM to transcribe.

    Returns (all_words, language, language_probability).
    """
    from faster_whisper import WhisperModel

    duration = _get_audio_duration(audio_path)
    model    = WhisperModel(model_name, device="cpu", compute_type="int8")

    tmp_dir = output_dir / f"_chunks_{audio_path.stem}"
    tmp_dir.mkdir(exist_ok=True)

    all_words              = []
    detected_language      = None
    detected_language_prob = None

    core_start = 0.0
    chunk_idx  = 0
    n_chunks   = max(1, math.ceil(duration / CHUNK_SEC))

    try:
        while core_start < duration:
            core_end  = min(core_start + CHUNK_SEC, duration)
            ext_start = max(0.0, core_start - OVERLAP_SEC)
            ext_end   = min(duration, core_end + OVERLAP_SEC)
            ext_len   = ext_end - ext_start

            chunk_idx += 1
            print(f"    \U0001f3a7  Transcribing chunk {chunk_idx}/{n_chunks} "
                  f"({ext_start/60:.1f}\u2013{ext_end/60:.1f} min)...")

            chunk_path = tmp_dir / f"chunk_{chunk_idx:03d}.wav"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-ss", f"{ext_start:.3f}",
                "-t",  f"{ext_len:.3f}",
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                str(chunk_path),
            ]
            _run_ffmpeg(cmd, quiet=True)

            segments, info = model.transcribe(
                str(chunk_path),
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                word_timestamps=True,
            )

            if detected_language is None:
                detected_language      = info.language
                detected_language_prob = info.language_probability

            is_first_chunk = (core_start == 0.0)
            is_last_chunk  = (core_end >= duration)

            for seg in segments:
                if not seg.words:
                    continue
                for w in seg.words:
                    cleaned = w.word.strip()
                    if not cleaned:
                        continue
                    abs_start = ext_start + w.start
                    abs_end   = ext_start + w.end

                    in_core = core_start <= abs_start < core_end
                    keep = (
                        in_core
                        or (is_first_chunk and abs_start < core_start)
                        or (is_last_chunk and abs_start >= core_end)
                    )
                    if keep:
                        all_words.append({"word": cleaned, "start": abs_start, "end": abs_end})

            chunk_path.unlink(missing_ok=True)
            core_start = core_end
    finally:
        try:
            tmp_dir.rmdir()
        except OSError:
            pass  # leftover files or already gone — not worth failing the run over

    all_words.sort(key=lambda w: w["start"])
    return all_words, detected_language, detected_language_prob


def transcribe_video(video_path: Path, model_name: str, output_dir: Path, words_per_line: int = 5, subtitle_delay: float = 0.2):
    """
    Run faster-whisper (chunked) with word_timestamps=True for per-word timing.
    This gives precise subtitle sync instead of splitting segments evenly.
    Returns (srt_path, all_words) — all_words is used downstream to derive
    per-clip titles from each clip's own transcript slice.
    """
    srt_path = output_dir / (video_path.stem + ".srt")
    words_json_path = srt_path.with_suffix(".words.json")

    if srt_path.exists():
        print(f"\u23e9  SRT already exists, skipping transcription \u279c {srt_path.name}")
        all_words = []
        if words_json_path.exists():
            with open(words_json_path, encoding="utf-8") as jf:
                all_words = json.load(jf).get("words", [])
        return srt_path, all_words

    print(f"\n\U0001f3d9\ufe0f  Transcribing with faster-whisper ({model_name} model) \u2026")
    print("    (This can take a few minutes depending on video length and your hardware)")

    # Extract audio first — much faster than decoding video in Whisper
    audio_path = _extract_audio(video_path, output_dir)

    all_words, language, language_prob = _transcribe_words_chunked(audio_path, model_name, output_dir)

    print(f"    Detected language: {language} (confidence: {language_prob:.0%})")
    print(f"    Got per-word timestamps for {len(all_words)} words")
    _write_srt_from_words(all_words, srt_path, words_per_chunk=words_per_line, delay=subtitle_delay)

    # Save per-word data for karaoke ASS generation
    with open(words_json_path, "w", encoding="utf-8") as jf:
        json.dump({"words": all_words, "words_per_chunk": words_per_line, "delay": subtitle_delay}, jf)

    print(f"\u2705  Subtitles written \u279c {srt_path.name}")
    return srt_path, all_words


def transcribe_audio_only(video_path: Path, model_name: str, output_dir: Path) -> list:
    """
    Transcribe the full video audio (chunked) and return the raw per-word list.
    Does NOT write an SRT — just returns words so hook scoring can run immediately.
    Saves a .words.json alongside for reuse on subsequent runs.
    """
    words_json_path = output_dir / (video_path.stem + ".words.json")
    if words_json_path.exists():
        print(f"\n⏩  Transcript already exists → {words_json_path.name}")
        with open(words_json_path, encoding="utf-8") as f:
            return json.load(f)["words"]

    print(f"\n🏙️  Transcribing audio for hook analysis ({model_name} model) …")
    print("    (audio-only pass — no video processing yet)")

    audio_path = _extract_audio(video_path, output_dir)

    all_words, language, language_prob = _transcribe_words_chunked(audio_path, model_name, output_dir)

    print(f"    Language: {language} ({language_prob:.0%})")
    print(f"    Got {len(all_words)} words")

    with open(words_json_path, "w", encoding="utf-8") as f:
        json.dump({"words": all_words, "words_per_chunk": 5, "delay": 0.0}, f)
    print(f"✅  Transcript saved → {words_json_path.name}")
    return all_words



# ─── MediaPipe face detector adapter ──────────────────────────────────────────

MEDIAPIPE_FACE_CONFIDENCE = 0.45
MEDIAPIPE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)


def _ensure_mediapipe_face_model() -> Path:
    """
    Download the official BlazeFace model once and reuse it on later runs.
    """
    import urllib.request

    model_dir = Path.home() / ".cache" / "yt_clip_processor" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / "blaze_face_short_range.tflite"
    if model_path.exists() and model_path.stat().st_size > 100_000:
        return model_path

    print("    📦  Downloading MediaPipe face model (one-time setup)...")
    temp_path = model_path.with_suffix(".download")

    try:
        urllib.request.urlretrieve(MEDIAPIPE_MODEL_URL, temp_path)
        temp_path.replace(model_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return model_path


def _create_mediapipe_face_detector():
    """
    Create MediaPipe Face Detector in VIDEO mode.

    The rest of the program still receives the original
    (center_x, center_y, width, height) tuple format.
    """
    import mediapipe as mp

    model_path = _ensure_mediapipe_face_model()

    options = mp.tasks.vision.FaceDetectorOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        min_detection_confidence=MEDIAPIPE_FACE_CONFIDENCE,
        min_suppression_threshold=0.30,
    )

    return mp.tasks.vision.FaceDetector.create_from_options(options)


def _detect_faces_mediapipe(
    detector,
    frame,
    timestamp_ms: int,
    src_w: int,
    src_h: int,
) -> list:
    """
    Detect faces and return the exact tuple format used by the old Haar code:
        (center_x, center_y, width, height)

    No continuity filtering or scene-mode filtering is applied here. That keeps
    the existing dual/reaction logic and thresholds unchanged.
    """
    import cv2
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=rgb,
    )

    result = detector.detect_for_video(mp_image, timestamp_ms)
    detected = []

    for detection in result.detections:
        if not detection.categories:
            continue

        confidence = float(detection.categories[0].score)
        if confidence < MEDIAPIPE_FACE_CONFIDENCE:
            continue

        box = detection.bounding_box

        x = max(0, int(box.origin_x))
        y = max(0, int(box.origin_y))
        w = max(1, min(int(box.width), src_w - x))
        h = max(1, min(int(box.height), src_h - y))

        # MediaPipe provides facial keypoints. Requiring several valid points
        # helps reject non-face graphics without changing scene strictness.
        valid_keypoints = sum(
            1
            for keypoint in (detection.keypoints or [])
            if 0.0 <= keypoint.x <= 1.0
            and 0.0 <= keypoint.y <= 1.0
        )
        if valid_keypoints < 3:
            continue

        detected.append(
            (
                x + w // 2,
                y + h // 2,
                w,
                h,
            )
        )

    detected.sort(
        key=lambda face: face[2] * face[3],
        reverse=True,
    )
    return detected[:2]


def sample_face_timestamps(video_path: Path, sample_every_sec: float = 1.0) -> set:
    """
    Quick MediaPipe face-presence pass over the full video.
    Samples one frame every `sample_every_sec`.
    Returns timestamps where at least one face was found.
    """
    try:
        import cv2
        detector = _create_mediapipe_face_detector()
    except Exception as exc:
        print(f"    ⚠️  MediaPipe unavailable — skipping face gate: {exc}")
        return set()

    print(f"\n👤  Sampling faces for hook gating with MediaPipe "
          f"(every {sample_every_sec}s)…")

    codec = _get_video_codec(video_path)
    if codec in ("av1", "vp9", "vp8", "hevc"):
        transcoded = video_path.parent / (video_path.stem + "_h264.mp4")

        if transcoded.exists():
            print(f"    ♻️  Reusing existing H264 transcode → {transcoded.name}")
        else:
            print(f"    ⚠️  Codec '{codec}' unsupported by OpenCV — "
                  f"transcoding to H264…")
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",
                str(transcoded),
            ]
            _run_ffmpeg(cmd, quiet=True)
            print(f"    ✅  Transcoded → {transcoded.name}")

        video_path = transcoded

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        detector.close()
        print("    ⚠️  Could not open video for face sampling")
        return set()

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(fps * sample_every_sec))

    face_times = set()
    frame_idx = 0
    sampled = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            timestamp_ms = int(round(frame_idx * 1000 / fps))
            detected = _detect_faces_mediapipe(
                detector,
                frame,
                timestamp_ms,
                src_w,
                src_h,
            )

            if detected:
                face_times.add(round(frame_idx / fps, 2))

            sampled += 1

        frame_idx += 1

    cap.release()
    detector.close()

    face_pct = 100 * len(face_times) / max(sampled, 1)
    print(
        f"    Face present in {len(face_times)}/{sampled} samples "
        f"({face_pct:.0f}%)"
    )
    return face_times


def process_hook_segment(
    source_video:  Path,
    hook:          dict,
    clip_length:   int,
    seg_dir:       Path,
    clip_path:     Path,
    all_words:     list,
    model_name:    str,
    words_per_line: int,
    subtitle_delay: float,
    font:          str,
    no_vertical:   bool,
    no_burn_subs:  bool,
    allowed_modes: set = None,
) -> bool:
    """
    Full pipeline for a single hook segment:
      1. Trim raw video to [start, start+clip_length]
      2. Reframe to vertical (or skip)
      3. Slice the global word list to this time window → write SRT + words.json
      4. Burn karaoke subtitles (or skip)
      5. Move final file to clip_path

    seg_dir is a temp working directory for this segment's intermediate files.
    Returns True on success.
    """
    seg_dir.mkdir(parents=True, exist_ok=True)

    start_sec = hook["start_sec"]
    end_sec   = hook["end_sec"]
    actual    = round(end_sec - start_sec, 2)

    # ── 1. Trim raw segment ──
    raw_seg = seg_dir / "raw.mp4"
    if not raw_seg.exists():
        # Use input seek (-ss after -i) + re-encode for frame-accurate cut.
        # -c copy with pre-input seek causes a keyframe misalignment glitch
        # on the first ~1s of the clip; re-encoding eliminates this entirely.
        cmd = [
            "ffmpeg", "-y",
            "-i", str(source_video),
            "-ss", str(start_sec),
            "-t", str(actual),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            str(raw_seg),
        ]
        _run_ffmpeg(cmd, quiet=True)

    # ── 2. Reframe to vertical ──
    if not no_vertical:
        working, face_info = reframe_to_vertical(raw_seg, seg_dir, allowed_modes=allowed_modes)
        if face_info:
            _fps = face_info.get("fps", 25)
            for s in face_info.get("scenes", []):
                s["start_sec"] = s["start"] / _fps
                s["end_sec"]   = s["end"]   / _fps
        scenes_for_subs = face_info.get("scenes") if face_info else None
    else:
        working         = raw_seg
        scenes_for_subs = None

    # ── 3. Slice words to this time window and re-zero timestamps ──
    seg_words = [
        {"word": w["word"],
         "start": round(w["start"] - start_sec, 3),
         "end":   round(w["end"]   - start_sec, 3)}
        for w in all_words
        if w["start"] >= start_sec - 0.1 and w["end"] <= end_sec + 0.5
    ]

    if not no_burn_subs and seg_words:
        srt_path        = seg_dir / "seg.srt"
        words_json_path = seg_dir / "seg.words.json"

        _write_srt_from_words(seg_words, srt_path,
                              words_per_chunk=words_per_line,
                              delay=subtitle_delay)
        with open(words_json_path, "w", encoding="utf-8") as f:
            json.dump({"words": seg_words,
                       "words_per_chunk": words_per_line,
                       "delay": subtitle_delay}, f)

        # ── 4. Burn subtitles ──
        final_seg = burn_subtitles(working, srt_path, seg_dir,
                                   font=font, scenes=scenes_for_subs)
    else:
        final_seg = working
        if no_burn_subs:
            print("    ⏩  Skipping subtitle burning (--no-burn-subs)")

    # ── 5. Move to final clip path ──
    import shutil as _sh
    _sh.move(str(final_seg), str(clip_path))
    return True



def _format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    hours   = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs    = int(seconds % 60)
    millis  = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt_from_words(words: list, path: Path, words_per_chunk: int = 5, delay: float = 0.0):
    """
    Build SRT from per-word timestamps.
    - Each chunk only shows while those words are being spoken
    - End time = last word end (not stretched to next chunk start)
    - Gap between chunks = silence = no subtitle on screen
    """
    with open(path, "w", encoding="utf-8") as f:
        index = 1
        i = 0
        while i < len(words):
            chunk = words[i:i + words_per_chunk]
            if not chunk:
                break

            start = max(0.0, chunk[0]["start"] + delay)
            # End exactly when last word finishes — no lingering during silence
            end   = max(start + 0.05, chunk[-1]["end"] + delay)

            # Extend end to next chunk's start so there's no blank frame gap
            if i + words_per_chunk < len(words):
                next_start = words[i + words_per_chunk]["start"] + delay
                end = max(end, next_start)

            text = " ".join(w["word"] for w in chunk).upper()

            f.write(
                f"{index}\n"
                f"{_format_timestamp(start)} --> {_format_timestamp(end)}\n"
                f"{text}\n\n"
            )
            index += 1
            i += words_per_chunk


def _write_srt(segments: list, path: Path, max_words: int = 5, delay: float = 0.0):
    """
    Fallback: write SRT from segment-level timestamps (less accurate).
    Used only if word_timestamps are unavailable.
    """
    with open(path, "w", encoding="utf-8") as f:
        index = 1
        for seg in segments:
            words = seg["text"].strip().split()
            if not words:
                continue

            seg_duration = seg["end"] - seg["start"]
            total_words  = len(words)

            # Time per word — distribute timing proportionally
            chunks = [words[i:i+max_words] for i in range(0, total_words, max_words)]
            chunk_duration = seg_duration / len(chunks)

            for j, chunk in enumerate(chunks):
                chunk_start = max(0.0, seg["start"] + j * chunk_duration + delay)
                chunk_end   = max(chunk_start + 0.1, seg["start"] + (j + 1) * chunk_duration + delay)
                text        = " ".join(chunk).upper()
                f.write(
                    f"{index}\n"
                    f"{_format_timestamp(chunk_start)} --> {_format_timestamp(chunk_end)}\n"
                    f"{text}\n\n"
                )
                index += 1


def _write_karaoke_ass(words_json_path: Path, ass_path: Path, font: str = "Arial",
                       scenes: list = None):
    """
    Write an ASS subtitle file with Opus-Clip-style karaoke highlighting.

    Layout
    ------
    • Each "chunk" of N words is shown as a single line for its full duration.
    • The currently-spoken word is yellow; all other words in the chunk are white.
    • This is achieved by emitting one Dialogue event *per word* in the chunk,
      each covering only that word's time window, with the full chunk text where
      only that word carries the yellow colour tag.  The events are stacked on
      the same layer so they replace each other seamlessly.

    Style
    -----
    • Font: bold, 88 px
    • Colour: white (#FFFFFF) base, yellow (#00FFFF in BGR = &H00FFFF& in ASS)
    • Outline: 4 px solid black — no shadow box
    • Position: bottom-center (alignment 2) with a 180 px bottom margin
    • Split-screen scenes use alignment 5 (middle-center, no margin)
    """
    import json as _json

    font_name = Path(font).stem if Path(font).suffix.lower() == ".ttf" else font

    with open(words_json_path, "r", encoding="utf-8") as jf:
        data = _json.load(jf)

    all_words       = data["words"]
    words_per_chunk = data.get("words_per_chunk", 5)
    delay           = data.get("delay", 0.0)

    # ── Scene lookup ──
    scene_ranges = scenes or []

    def _style_for_time(t: float) -> str:
        for s in scene_ranges:
            s0 = s.get("start_sec", s.get("start", 0))
            s1 = s.get("end_sec",   s.get("end", float("inf")))
            if s0 <= t < s1:
                return "Split" if s.get("mode") in ("dual", "reaction") else "Default"
        return "Default"

    # ── Timestamp helpers ──
    def _sec_to_ass(sec: float) -> str:
        sec  = max(0.0, sec)
        h    = int(sec // 3600)
        m    = int((sec % 3600) // 60)
        s    = int(sec % 60)
        cs   = int(round((sec - int(sec)) * 100))   # centiseconds
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # ── ASS colour constants (BGR order, &HAABBGGRR&, AA=00 = opaque) ──
    WHITE  = "&H00FFFFFF&"
    YELLOW = "&H0000FFFF&"   # pure yellow in BGR = 00,FF,FF → &H0000FFFF&

    # ── Header ──
    style_fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    # BorderStyle 1 = outline+shadow (we set Shadow=0 → outline only)
    # MarginL/R = 60px each side to prevent text clipping on narrow displays/reposts
    # MarginV (Default) = 420px ≈ 1/4 up from bottom, clear of TikTok caption bar
    def _style_line(name, alignment, margin_v):
        return (
            f"Style: {name},{font_name},52,{WHITE},{WHITE},&H00000000&,&H00000000&,"
            f"-1,0,0,0,100,100,0,0,1,4,0,{alignment},40,40,{margin_v},1\n"
        )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 720\n"
        "PlayResY: 1280\n"
        "\n"
        "[V4+ Styles]\n"
        f"{style_fmt}"
        + _style_line("Default", 2, 280)   # ~1/4 up from bottom, above TikTok caption
        + _style_line("Split",   5, 0)     # middle-center (split-screen)
        + "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    # ── Build chunks ──
    dialogue_lines = []

    i = 0
    while i < len(all_words):
        chunk = all_words[i : i + words_per_chunk]
        if not chunk:
            break

        chunk_start = max(0.0, chunk[0]["start"] + delay)
        chunk_end   = max(chunk_start + 0.05, chunk[-1]["end"] + delay)

        # Extend to next chunk's start (no blank gap between chunks)
        if i + words_per_chunk < len(all_words):
            next_start  = all_words[i + words_per_chunk]["start"] + delay
            chunk_end   = max(chunk_end, next_start)

        style = _style_for_time(chunk_start)

        # Upper-case display words
        display = [w["word"].upper() for w in chunk]

        # Emit one Dialogue event per word in the chunk.
        # Each event spans only that word's active time window.
        for j, word_data in enumerate(chunk):
            w_start = max(0.0, word_data["start"] + delay)
            # Word is "active" until the next word begins (or chunk ends)
            if j + 1 < len(chunk):
                w_end = max(w_start + 0.04, chunk[j + 1]["start"] + delay)
            else:
                w_end = chunk_end

            # Build the full line: words before active = white (default),
            # active word = yellow, words after = white (slightly dimmed via alpha)
            parts = []
            for k, dw in enumerate(display):
                if k < j:
                    # Already spoken — white but slightly transparent (70%)
                    parts.append(f"{{\\c{WHITE}\\alpha&H46&}}{dw}{{\\alpha&H00&}}")
                elif k == j:
                    # Currently spoken — yellow, fully opaque
                    parts.append(f"{{\\c{YELLOW}}}{dw}{{\\c{WHITE}}}")
                else:
                    # Not yet spoken — white, full opacity
                    parts.append(dw)

            text = " ".join(parts)
            dialogue_lines.append(
                f"Dialogue: 0,{_sec_to_ass(w_start)},{_sec_to_ass(w_end)},"
                f"{style},,0,0,0,,{text}"
            )

        i += words_per_chunk

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(dialogue_lines))
        f.write("\n")


# ─── Step 3: Reframe to vertical 9:16 + burn subtitles ───────────────────────

def reframe_to_vertical(video_path: Path, output_dir: Path, allowed_modes: set = None):
    """
    Smart reframe to 9:16 vertical.
    Returns (vertical_path, face_info). face_info is None if already cached.
    - 2 faces consistently present -> split-screen mode (top/bottom halves)
    - 1 face -> single face tracking mode
    - 0 faces -> center crop fallback
    """
    vertical_path = output_dir / (video_path.stem + "_vertical.mp4")

    if vertical_path.exists():
        print(f"\u23e9  Vertical video already exists \u279c {vertical_path.name}")
        return vertical_path, None  # face_info not available for cached output

    print(f"\n\U0001f4f1  Reframing to 9:16...")

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("    \u26a0\ufe0f  opencv not installed \u2014 falling back to center crop.")
        return _reframe_center_crop(video_path, output_dir), None

    # ── Check codec — OpenCV cannot decode AV1, transcode first ──
    codec_name = _get_video_codec(video_path)
    if codec_name in ("av1", "vp9", "vp8", "hevc"):
        print(f"    \u26a0\ufe0f  Codec '{codec_name}' not supported by OpenCV — transcoding to h264...")
        transcoded = output_dir / (video_path.stem + "_h264.mp4")
        if not transcoded.exists():
            cmd = [
                "ffmpeg", "-y", "-i", str(video_path),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "192k", str(transcoded),
            ]
            _run_ffmpeg(cmd, quiet=True)
            print(f"    \u2705  Transcoded \u279c {transcoded.name}")
        working_path = transcoded
    else:
        working_path = video_path

    # ── Get video properties ──
    cap   = cv2.VideoCapture(str(working_path))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # If OpenCV couldn't read dimensions, the codec is unsupported regardless
    # of what ffprobe reported — force a transcode to h264 and retry.
    if src_w == 0 or src_h == 0:
        print(f"    \u26a0\ufe0f  OpenCV couldn't read video (0x0) — forcing h264 transcode...")
        transcoded = output_dir / (video_path.stem + "_h264.mp4")
        if not transcoded.exists():
            cmd = [
                "ffmpeg", "-y", "-i", str(working_path),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "192k", str(transcoded),
            ]
            _run_ffmpeg(cmd, quiet=True)
            print(f"    \u2705  Transcoded \u279c {transcoded.name}")
        working_path = transcoded
        cap   = cv2.VideoCapture(str(working_path))
        fps   = cap.get(cv2.CAP_PROP_FPS) or 25
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        if src_w == 0 or src_h == 0:
            print(f"    \u26a0\ufe0f  Still can't read video after transcode — falling back to center crop.")
            return _reframe_center_crop(video_path, output_dir), None

    sample_every = max(1, int(fps * 1.0))
    print(f"    Source: {src_w}x{src_h} | Sampling every {sample_every} frames")
    _modes_for_log = allowed_modes if allowed_modes else {'single', 'dual', 'reaction'}
    print(f"    Scene types searched: {', '.join(sorted(_modes_for_log))}")

    # ── Analyse faces ──
    face_info = analyse_faces(working_path, sample_every=sample_every, allowed_modes=allowed_modes)

    has_dual     = any(s["mode"] == "dual"     for s in face_info.get("scenes", []))
    has_reaction = any(s["mode"] == "reaction" for s in face_info.get("scenes", []))

    if has_dual or has_reaction:
        # Scene-aware render: auto-switches between split-screen, reaction, and single-face
        kinds = " + ".join(k for k, v in (("dual", has_dual), ("reaction", has_reaction)) if v)
        print(f"    \U0001f465  {kinds.capitalize()} scene(s) detected \u2014 scene-aware render...")
        speaking_data = detect_lip_movement(
            working_path, face_info["face_data"], fps, sample_every
        )
        success = render_split_screen(
            working_path, vertical_path,
            face_info["face_data"], speaking_data,
            fps, src_w, src_h, sample_every,
            scenes=face_info["scenes"],
        )
        if success:
            print(f"\u2705  Scene-aware vertical video \u279c {vertical_path.name}")
            return vertical_path, face_info
        print("    \u26a0\ufe0f  Scene render failed, falling back to single tracking")

    # ── SINGLE FACE ONLY ──
    print(f"    \U0001f464  Single face mode \u2014 tracking speaker...")
    crop_w    = min(int(src_h * 9 / 16), src_w)
    default_x = (src_w - crop_w) // 2

    keyframes = {}
    for frame_idx, faces in face_info["face_data"].items():
        if faces:
            first = list(faces.values())[0] if isinstance(faces, dict) else faces[0]
            face_cx = first[0]
            raw_x   = face_cx - crop_w // 2
            keyframes[frame_idx] = max(0, min(raw_x, src_w - crop_w))
        else:
            keyframes[frame_idx] = None

    if not any(v is not None for v in keyframes.values()):
        print("    No faces found \u2014 falling back to center crop")
        return _reframe_center_crop(working_path, output_dir), face_info

    all_crop_x = _smooth_crop_path(keyframes, total, sample_every, default_x)
    print(f"    Rendering face-tracked video (this takes a while)...")
    success = _render_with_tracking(working_path, vertical_path, all_crop_x, crop_w, src_h, fps, face_data=face_info.get('face_data'), sample_every=sample_every)

    if not success:
        print("    \u26a0\ufe0f  Render failed, falling back to center crop")
        return _reframe_center_crop(video_path, output_dir), face_info

    print(f"\u2705  Face-tracked vertical video \u279c {vertical_path.name}")
    return vertical_path, face_info



def _render_with_tracking(
    video_path: Path,
    out_path: Path,
    crop_x_list: list,
    crop_w: int,
    src_h: int,
    fps: float,
    face_data: dict = None,   # keyframe→face dict from analyse_faces(), used to gate letterbox
    sample_every: int = 14,
) -> bool:
    """
    Use ffmpeg with a crop filter_complex script file to apply per-frame cropping.
    We write crop positions as a ffmpeg -vf crop expression that changes over time
    using the 'crop' filter with expressions referencing 'n' (frame number).

    For smooth tracking we write the crop_x values into a temp data file and use
    a Python-side approach: render via opencv, write raw frames, pipe to ffmpeg.
    """
    try:
        import cv2
        import numpy as np
        import subprocess

        cap = cv2.VideoCapture(str(video_path))

        # ffmpeg process to receive raw BGR frames via stdin
        cmd_in = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", "1080x1920",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "pipe:0",
            # re-add audio from original
            "-i", str(video_path),
            "-map", "0:v",
            "-map", "1:a",
            # yuv420p is required for broad player compatibility
            # (Windows Media Player, phones, TikTok, etc.)
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",  # web/mobile streaming optimisation
            "-c:a", "aac",              # aac is more universally supported than copy
            "-b:a", "192k",
            "-shortest",
            str(out_path),
        ]

        proc = subprocess.Popen(cmd_in, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        frame_idx    = 0
        report_every = max(1, int(fps * 10))  # print progress every 10s

        # ── On-screen text / chyron detection ────────────────────────────────
        # When a chyron or lower-third graphic is detected, we zoom out by
        # expanding the source crop symmetrically around the face-tracked
        # center — the face tracker is never touched, only the crop width/height
        # grows outward from the center point it already computed.
        #
        # Key fix vs previous version: the face tracker outputs a LEFT EDGE (x)
        # for a fixed crop_w window.  We convert that to a CENTER, do all zoom
        # math in center-space, then convert back to a left edge at render time.
        # This means the face tracker and zoom system are completely independent.
        TEXT_SAMPLE_EVERY = max(1, int(fps * 0.5))   # sample twice per second
        last_text_frame   = -999
        TEXT_HOLD_FRAMES  = int(fps * 1.5)  # hold letterbox 1.5s after text gone

        # Build a fast face-presence lookup from the pre-computed face_data.
        # Keys are sampled keyframe indices; we'll check the nearest keyframe
        # to the current frame_idx to decide if a face is present.
        _fd          = face_data or {}
        _fd_keys     = sorted(_fd.keys())
        _sample_ev   = sample_every or 14

        def _face_present_at(fidx: int) -> bool:
            """Return True if a face was detected at or near this frame index."""
            if not _fd_keys:
                return False
            # Find the nearest sampled keyframe
            nearest = min(_fd_keys, key=lambda k: abs(k - fidx))
            return len(_fd.get(nearest, {})) > 0

        def _detect_chyron(frm):
            """
            Detect a news chyron / lower-third graphic using a loosened
            scoring approach — needs score >= 2 from four signals.
            """
            h, w = frm.shape[:2]
            roi  = frm[int(h * 0.65):, :]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            score = 0

            # Signal 1: edge density
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.count_nonzero(edges) / max(edges.size, 1)
            if edge_density > 0.04:
                score += 2
            elif edge_density > 0.02:
                score += 1

            # Signal 2: horizontal edges dominate (text lines are horizontal)
            sobel_h  = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            sobel_v  = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            h_energy = float(np.mean(np.abs(sobel_h)))
            v_energy = float(np.mean(np.abs(sobel_v))) + 1e-6
            if (h_energy / v_energy) > 1.3:
                score += 1

            # Signal 3: high local contrast
            if float(np.std(gray)) > 45:
                score += 1

            # Signal 4: at least one very uniform row (solid bg behind text)
            strip    = gray[gray.shape[0] // 2 :, :]
            row_stds = np.std(strip, axis=1)
            if float(np.min(row_stds)) < 30:
                score += 1

            return score >= 2

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            src_h_frame = frame.shape[0]
            src_w_frame = frame.shape[1]

            # ── Text detection (sampled) ──
            # Only trigger letterbox when NO face is detected at this frame.
            # If a face is present, the chyron detection is almost certainly a
            # false positive from background detail or studio graphics.
            if frame_idx % TEXT_SAMPLE_EVERY == 0:
                face_here = _face_present_at(frame_idx)
                if not face_here and _detect_chyron(frame):
                    last_text_frame = frame_idx

            text_visible = (frame_idx - last_text_frame) <= TEXT_HOLD_FRAMES

            # ── Face-tracked center ──
            tracked_left  = crop_x_list[frame_idx] if frame_idx < len(crop_x_list) else crop_x_list[-1]
            face_center_x = tracked_left + crop_w // 2

            # ── Render mode: letterbox full frame or normal face-tracked crop ──
            if text_visible:
                # Letterbox: full source frame scaled to fit 1080×1920 with black bars
                scale     = 1080 / src_w_frame
                scaled_h  = int(src_h_frame * scale)
                pad_top   = (1920 - scaled_h) // 2
                scaled    = cv2.resize(frame, (1080, scaled_h), interpolation=cv2.INTER_LINEAR)
                resized   = np.zeros((1920, 1080, 3), dtype=np.uint8)
                resized[pad_top : pad_top + scaled_h, :] = scaled
            else:
                # Normal face-tracked 9:16 crop
                x = int(face_center_x - crop_w // 2)
                x = max(0, min(x, src_w_frame - crop_w))
                cropped = frame[:, x : x + crop_w]
                resized = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LINEAR)

            proc.stdin.write(resized.tobytes())

            if frame_idx % report_every == 0:
                secs      = frame_idx / fps
                mode_info = " [letterbox]" if text_visible else ""
                print(f"    \u23f1\ufe0f  {int(secs//60)}:{int(secs%60):02d} processed...{mode_info}")

            frame_idx += 1

        proc.stdin.close()
        proc.wait()
        cap.release()
        return proc.returncode == 0

    except Exception as e:
        print(f"    Render error: {e}")
        return False


def _smooth_crop_path(keyframes: dict, total_frames: int, sample_every: int, default_x: int) -> list:
    """
    Convert sparse keyframe positions into a smooth per-frame list.
    Linearly interpolates between keyframes, then gaussian-smooths.
    """
    raw = {k: v for k, v in keyframes.items() if v is not None}

    if not raw:
        return [default_x] * total_frames

    sorted_keys = sorted(raw.keys())
    result = []

    for i in range(total_frames):
        before = [k for k in sorted_keys if k <= i]
        after  = [k for k in sorted_keys if k > i]
        if before and after:
            k1, k2 = before[-1], after[0]
            t = (i - k1) / (k2 - k1)
            x = int(raw[k1] + t * (raw[k2] - raw[k1]))
        elif before:
            x = raw[before[-1]]
        elif after:
            x = raw[after[0]]
        else:
            x = default_x
        result.append(x)

    # Smooth with gaussian to remove jitter — sigma ~= 1 second of frames
    try:
        import numpy as np
        from scipy.ndimage import gaussian_filter1d
        arr     = np.array(result, dtype=float)
        result  = [int(v) for v in gaussian_filter1d(arr, sigma=25)]
    except ImportError:
        # scipy not available — do simple moving average instead
        window = 25
        smoothed = []
        for i in range(len(result)):
            lo = max(0, i - window)
            hi = min(len(result), i + window + 1)
            smoothed.append(int(sum(result[lo:hi]) / (hi - lo)))
        result = smoothed

    return result


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


def _detect_faces_opencv_dnn(video_path_str: str, src_w: int, src_h: int, crop_w: int, sample_every: int) -> dict:
    """
    Fallback face detector using OpenCV's built-in DNN face detector.
    Works without mediapipe solutions API.
    """
    import cv2
    import urllib.request
    import os

    # Use OpenCV's built-in Haar cascade — no download needed
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(video_path_str)
    keyframes = {}
    frame_idx = 0
    default_x = (src_w - crop_w) // 2

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces) > 0:
                # Use largest face
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                face_cx = x + w // 2
                raw_x   = face_cx - crop_w // 2
                keyframes[frame_idx] = max(0, min(raw_x, src_w - crop_w))
            else:
                keyframes[frame_idx] = None
        frame_idx += 1

    cap.release()
    return keyframes


def _reframe_center_crop(video_path: Path, output_dir: Path) -> Path:
    """Fallback: plain center crop to 9:16 via ffmpeg."""
    vertical_path = output_dir / (video_path.stem + "_vertical.mp4")
    if vertical_path.exists():
        return vertical_path
    print(f"\n\U0001f4f1  Center-cropping to 9:16 (1080x1920)...")
    vf  = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        str(vertical_path),
    ]
    _run_ffmpeg(cmd)
    print(f"\u2705  Vertical video \u279c {vertical_path.name}")
    return vertical_path


# ─── Dual-face split screen ───────────────────────────────────────────────────

# A reaction-cam face bubble is both small (relative to frame height) and
# off-center (clustered toward a corner). A "true" single-person shot has a
# face that's large and roughly centered. Both cases detect exactly one face,
# so face count alone can't tell them apart — size/position does.
REACTION_MAX_FACE_HEIGHT_RATIO = 0.26   # face height above this = fills the frame, not a bubble
REACTION_MIN_OFFCENTER_RATIO   = 0.45   # normalized distance from center to count as "in a corner"


def _is_reaction_face(face_box: tuple, src_w: int, src_h: int) -> bool:
    """
    Classify a single detected face as a reaction camera only when BOTH
    requirements are satisfied:

    1. The face is smaller than REACTION_MAX_FACE_HEIGHT_RATIO.
    2. The face is farther from the horizontal (x-axis) center than
       REACTION_MIN_OFFCENTER_RATIO. Reaction bubbles in this pipeline are
       always positioned to the side (left/right), never top/bottom, so
       only horizontal offset counts — a face that's vertically off-center
       but horizontally centered (e.g. framed low in a wide shot) should
       NOT qualify.

    face_box is (cx, cy, w, h) in source-pixel coordinates.
    """
    cx, cy, w, h = face_box

    face_height_ratio = h / max(src_h, 1)

    offcenter_ratio = abs(cx - src_w / 2) / max(src_w / 2, 1)

    face_is_small_enough = (
        face_height_ratio < REACTION_MAX_FACE_HEIGHT_RATIO
    )
    face_is_far_enough_from_center = (
        offcenter_ratio > REACTION_MIN_OFFCENTER_RATIO
    )

    return (
        face_is_small_enough
        and face_is_far_enough_from_center
    )


def analyse_faces(video_path: Path, sample_every: int = 14, allowed_modes: set = None) -> dict:
    """
    Analyse faces per keyframe with stable identity tracking.
    Uses X-position clustering to assign consistent face IDs (left/right)
    rather than sorting by Y (which causes swapping in side-by-side shots).
    Also detects scene segments: sequences of single vs dual vs reaction face mode.

    allowed_modes: which scene types to actually search for, e.g. {'single', 'dual'}.
    Defaults to all three if None. Any raw classification for a disallowed mode
    (dual/reaction) falls back to 'single' — 'single' itself can't be disabled
    since it's the baseline crop used whenever nothing else applies.
    """
    if allowed_modes is None:
        allowed_modes = {'single', 'dual', 'reaction'}

    import cv2

    cap    = cv2.VideoCapture(str(video_path))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 25
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    detector = _create_mediapipe_face_detector()

    # ── Pass 1: raw MediaPipe face detection ──
    # This intentionally preserves the original raw_faces structure and does
    # not add target-switch delays or carry-forward boxes. Dual/reaction scene
    # detection therefore behaves exactly as it did before the detector swap.
    raw_faces = {}
    cap = cv2.VideoCapture(str(video_path))
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_every == 0:
            timestamp_ms = int(round(frame_idx * 1000 / fps))
            detected = _detect_faces_mediapipe(
                detector,
                frame,
                timestamp_ms,
                src_w,
                src_h,
            )

            # Duplicate guard: only collapse two boxes down to one when they
            # substantially OVERLAP (IoU) — that's the actual signature of
            # MediaPipe double-detecting the same face (NMS failure).
            #
            # The previous version used raw distance ("too close") and
            # relative size ("second too small") as proxies for "duplicate".
            # Both proxies also match perfectly legitimate footage: a real
            # reaction-cam bubble is SUPPOSED to be small relative to the
            # main face, and real dual-speaker shots are often centered and
            # close together. That meant genuine reaction/dual frames were
            # being silently collapsed to a single (larger) face before the
            # scene classifier in Pass 3 ever saw them — so dual/reaction
            # mode could never trigger no matter how the video looked.
            if len(detected) == 2:
                face_a, face_b = detected

                def _bbox(f):
                    cx, cy, w, h = f
                    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

                def _iou(b1, b2):
                    xa, ya = max(b1[0], b2[0]), max(b1[1], b2[1])
                    xb, yb = min(b1[2], b2[2]), min(b1[3], b2[3])
                    inter = max(0, xb - xa) * max(0, yb - ya)
                    area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
                    area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
                    union = area1 + area2 - inter
                    return inter / union if union > 0 else 0.0

                if _iou(_bbox(face_a), _bbox(face_b)) > 0.35:
                    detected = detected[:1]

            raw_faces[frame_idx] = detected

        frame_idx += 1

    cap.release()
    detector.close()

    # ── Pass 2: stable identity assignment ──
    # For dual frames, assign face_id=0 (LEFT) and face_id=1 (RIGHT) by X position.
    # This is stable across frames — left face stays left, right face stays right.
    # Works for side-by-side interviews and also top/bottom (uses X as tiebreaker).
    face_data = {}   # frame_idx -> {0: (cx,cy,w,h), 1: (cx,cy,w,h)}  or  {0: ...}

    for frame_idx, faces in raw_faces.items():
        if len(faces) == 0:
            face_data[frame_idx] = {}
        elif len(faces) == 1:
            face_data[frame_idx] = {0: faces[0]}
        else:
            # Assign by X: smaller X = face 0 (left), larger X = face 1 (right)
            sorted_by_x = sorted(faces, key=lambda f: f[0])
            face_data[frame_idx] = {0: sorted_by_x[0], 1: sorted_by_x[1]}

    # ── Pass 3: scene segmentation ──
    # Group consecutive keyframes into segments by face count
    # Require MIN_DURATION seconds before switching mode to avoid flicker
    # Require 6s of continuous dual-face before triggering split-screen
    # Only need 1.5s of single-face to revert — cutaways exit split quickly
    MIN_DUAL_FRAMES     = int((fps / sample_every) * 3.0)   # 3s of continuous 2-faces to enter split-screen
    MIN_SINGLE_FRAMES   = int((fps / sample_every) * 2.5)   # 2.5s of single-face to exit (covers jump cuts)
    MIN_REACTION_FRAMES = int((fps / sample_every) * 6.0)   # 6s of continuous small/off-center face to
                                                              # enter reaction mode. A real reaction-cam
                                                              # bubble sits in a fixed spot for the whole
                                                              # scene; a person briefly at the frame edge
                                                              # or a quick zoom-out only lasts a few seconds.
                                                              # 6s is long enough to filter those blips out
                                                              # without missing genuine sustained overlays.

    dual_count     = sum(1 for v in face_data.values() if len(v) == 2)
    reaction_count = sum(
        1 for v in face_data.values()
        if len(v) == 1 and _is_reaction_face(v[0], src_w, src_h)
    )
    single_count   = sum(1 for v in face_data.values() if len(v) == 1) - reaction_count
    total_sampled  = len(face_data)
    dual_ratio     = dual_count / max(total_sampled, 1)
    overall_mode   = 'dual' if dual_ratio > 0.60 else 'single'

    # Diagnostic: show how close the single-classified faces came to
    # passing the reaction test. If height ratios are clustering just
    # above REACTION_MAX_FACE_HEIGHT_RATIO (or offcenter ratios just below
    # REACTION_MIN_OFFCENTER_RATIO), that's the threshold to nudge next —
    # rather than guessing blind again.
    _single_faces = [v[0] for v in face_data.values() if len(v) == 1
                      and not _is_reaction_face(v[0], src_w, src_h)]
    if _single_faces:
        _heights = sorted(
            (h / max(src_h, 1)) for (_, _, _, h) in _single_faces
        )
        _offcenters = sorted(
            abs(cx - src_w / 2) / max(src_w / 2, 1)
            for (cx, cy, _, _) in _single_faces
        )
        mid_h = _heights[len(_heights) // 2]
        mid_o = _offcenters[len(_offcenters) // 2]
        print(f"    🔍  Single-face diagnostic (n={len(_single_faces)}): "
              f"height_ratio min/median/max = {_heights[0]:.2f}/{mid_h:.2f}/{_heights[-1]:.2f}  "
              f"(reaction needs < {REACTION_MAX_FACE_HEIGHT_RATIO})  |  "
              f"offcenter_ratio min/median/max = {_offcenters[0]:.2f}/{mid_o:.2f}/{_offcenters[-1]:.2f}  "
              f"(reaction needs > {REACTION_MIN_OFFCENTER_RATIO})")

    print(f"    Keyframe breakdown: {dual_count} dual, {single_count} single, {reaction_count} reaction, "
          f"{total_sampled - dual_count - single_count - reaction_count} empty  "
          f"(MIN_DUAL={MIN_DUAL_FRAMES} kf, MIN_SINGLE={MIN_SINGLE_FRAMES} kf, MIN_REACTION={MIN_REACTION_FRAMES} kf)")

    # Build per-keyframe mode sequence then smooth it
    keyframe_modes = {}
    for fidx in sorted(face_data.keys()):
        faces = face_data[fidx]
        if len(faces) == 2 and 'dual' in allowed_modes:
            keyframe_modes[fidx] = 'dual'
        elif len(faces) == 1 and 'reaction' in allowed_modes and _is_reaction_face(faces[0], src_w, src_h):
            keyframe_modes[fidx] = 'reaction'
        else:
            keyframe_modes[fidx] = 'single'

    mode_thresholds = {
        'dual':     MIN_DUAL_FRAMES,
        'single':   MIN_SINGLE_FRAMES,
        'reaction': MIN_REACTION_FRAMES,
    }
    smoothed_modes = _smooth_mode_sequence(keyframe_modes, mode_thresholds)

    # Build scene list: [{start_frame, end_frame, mode}]
    scenes = _build_scenes(smoothed_modes, sample_every, total)

    print(f"    Face analysis: {dual_count}/{total_sampled} dual frames ({dual_ratio:.0%})")
    print(f"    Detected {len(scenes)} scene(s): " +
          ", ".join(f"{s['mode']}@{int(s['start']/fps)}s" for s in scenes))

    return {
        'mode':         overall_mode,
        'face_data':    face_data,
        'scenes':       scenes,
        'fps':          fps,
        'src_w':        src_w,
        'src_h':        src_h,
        'total_frames': total,
        'sample_every': sample_every,
    }


def _smooth_mode_sequence(keyframe_modes: dict, mode_thresholds: dict) -> dict:
    """
    Apply hysteresis to mode transitions to prevent rapid flickering.
    A switch TO any given mode only fires after `mode_thresholds[mode]`
    consecutive keyframes have raw-classified as that mode.

    Works for an arbitrary set of modes (single/dual/reaction/...), keyed by
    `mode_thresholds`. Any mode not present in the dict falls back to a
    threshold of 1 (commits immediately).

    Key fix: the run counter tracks consecutive frames of the *pending* mode
    (the one we haven't committed to yet). It resets only when the raw signal
    flips back to the current committed mode — breaking the pending streak.
    This correctly ignores brief blips in either direction.
    """
    keys = sorted(keyframe_modes.keys())
    if not keys:
        return {}

    raw_seq  = [keyframe_modes[k] for k in keys]
    result   = {}
    cur_mode = 'single'   # always start in single — other modes must be earned via threshold

    # Sliding-window vote instead of a strict "N consecutive" counter.
    # A strict consecutive counter resets to zero on ANY single frame that
    # doesn't match (a blink, a head turn, a momentary confidence dip below
    # the detector threshold) — which on real footage sampled once a second
    # means dual/reaction can accumulate 2 good samples, drop one, and never
    # reach the threshold at all. Here we instead commit to a candidate mode
    # once it has occurred `threshold` times within the last
    # `threshold + TOLERANCE` samples, so a few dropped detections don't
    # permanently block a genuinely sustained dual/reaction scene.
    TOLERANCE = 2

    for idx, k in enumerate(keys):
        raw = raw_seq[idx]
        if raw != cur_mode:
            threshold = mode_thresholds.get(raw, 1)
            window    = threshold + TOLERANCE
            recent    = raw_seq[max(0, idx - window + 1): idx + 1]
            if recent.count(raw) >= threshold:
                cur_mode = raw
        result[k] = cur_mode

    return result


def _build_scenes(smoothed_modes: dict, sample_every: int, total_frames: int) -> list:
    """Convert per-keyframe modes into a list of scene dicts."""
    keys   = sorted(smoothed_modes.keys())
    scenes = []
    if not keys:
        return [{'start': 0, 'end': total_frames, 'mode': 'single'}]

    cur_mode  = smoothed_modes[keys[0]]
    cur_start = keys[0]

    for k in keys[1:]:
        if smoothed_modes[k] != cur_mode:
            scenes.append({'start': cur_start, 'end': k, 'mode': cur_mode})
            cur_mode  = smoothed_modes[k]
            cur_start = k

    scenes.append({'start': cur_start, 'end': total_frames, 'mode': cur_mode})
    return scenes


def detect_lip_movement(video_path: Path, face_data: dict, fps: float, sample_every: int) -> dict:
    """
    Detect which face (0=left, 1=right) is speaking using mouth-region motion.
    Uses stable face IDs from face_data (assigned by X position, not Y sort).
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    speaking  = {}
    prev_mouth = {0: None, 1: None}

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_every == 0:
            faces = face_data.get(frame_idx, {})
            if len(faces) == 2:
                energies = {}
                for fid, (cx, cy, fw, fh) in faces.items():
                    mouth_y1 = max(0, int(cy + fh * 0.1))
                    mouth_y2 = min(frame.shape[0], int(cy + fh * 0.45))
                    mouth_x1 = max(0, cx - fw//2)
                    mouth_x2 = min(frame.shape[1], cx + fw//2)
                    roi = frame[mouth_y1:mouth_y2, mouth_x1:mouth_x2]
                    if roi.size == 0:
                        energies[fid] = 0
                        continue
                    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    if prev_mouth[fid] is not None and prev_mouth[fid].shape == gray_roi.shape:
                        energies[fid] = float(np.mean(cv2.absdiff(gray_roi, prev_mouth[fid])))
                    else:
                        energies[fid] = 0
                    prev_mouth[fid] = gray_roi

                if energies and max(energies.values()) > 1.5:
                    speaking[frame_idx] = max(energies, key=energies.get)
                else:
                    speaking[frame_idx] = None
            else:
                speaking[frame_idx] = None

        frame_idx += 1

    cap.release()
    return speaking


def render_split_screen(
    video_path: Path,
    out_path: Path,
    face_data: dict,
    speaking_data: dict,
    fps: float,
    src_w: int,
    src_h: int,
    sample_every: int,
    scenes: list = None,
) -> bool:
    """
    Render with scene-aware mode switching:
    - Dual scenes:     stable split-screen (left face top, right face bottom)
    - Reaction scenes: split-screen (zoomed face bubble top, content bottom)
    - Single scenes:   full-frame face tracking
    Faces are identified by X position (left=0, right=1) so they never swap.
    `scenes` must be the smoothed scene list from analyse_faces() — if omitted,
    falls back to raw face_data (legacy behaviour, prone to jump-cut flicker,
    and without src_w/src_h it can't distinguish reaction from single).
    """
    import cv2
    import numpy as np
    import subprocess

    OUT_W, OUT_H = 720, 1280
    HALF_H       = OUT_H // 2
    CROP_W       = OUT_W

    # Build per-keyframe mode lookup from the SMOOTHED scenes list.
    # This is critical — using raw face_data here bypasses all the hysteresis
    # work done in _smooth_mode_sequence and causes jump-cut false positives.
    if scenes:
        scene_mode_per_frame = {}
        for kf in sorted(face_data.keys()):
            kf_sec = kf / fps
            mode = 'single'
            for s in scenes:
                if s['start'] <= kf < s['end']:
                    mode = s['mode']
                    break
            scene_mode_per_frame[kf] = mode
    else:
        # Fallback: derive from raw face_data (legacy)
        scene_mode_per_frame = _build_scene_mode_lookup(face_data, sample_every, src_w, src_h)

    sorted_kf   = sorted(scene_mode_per_frame.keys())
    boundaries  = []
    prev_mode   = None
    for kf in sorted_kf:
        m = scene_mode_per_frame[kf]
        if prev_mode is not None and m != prev_mode:
            boundaries.append(kf)   # frame where mode flips
        prev_mode = m

    print(f"    Scene cuts at frames: {boundaries if boundaries else 'none (single mode throughout)'}")

    # Build smooth per-frame positions for SINGLE-face scenes only.
    # For dual/split scenes we lock the crop at the first detected frame of
    # that scene and hold it for the entire duration — no panning.
    pos = {}
    for fid in [0, 1]:
        pos[fid] = {
            'x': _build_smooth_positions(face_data, fid, 'x', src_w // 2, src_w, sample_every, boundaries),
            'y': _build_smooth_positions(face_data, fid, 'y', src_h // 2, src_h, sample_every, boundaries),
        }

    # ── Pre-compute anchor boxes for each dual scene ──
    # For each dual scene, find the first keyframe with two face detections and
    # lock a fixed crop box for each person for the entire scene.
    # The box is centered on the detected face, clamped to that person's half
    # of the source frame, and never moves again — like a news broadcast layout.
    # Single-face scenes use the smooth tracking path (pos[]) instead.
    CROP_W_HALF = src_w // 2
    CROP_H_HALF = int(src_h * 0.8)

    anchor_boxes = {}   # scene_start_frame -> {0: (x1,y1,x2,y2), 1: (x1,y1,x2,y2)}

    def _make_box(cx, cy, box_w, box_h, x_min, x_max):
        """Build a clamped crop box centered on (cx, cy) within [x_min, x_max]."""
        x1 = max(x_min, min(cx - box_w // 2, x_max - box_w))
        x2 = x1 + box_w
        y1 = max(0, min(cy - box_h // 2, src_h - box_h))
        y2 = y1 + box_h
        return (x1, y1, x2, y2)

    # Reaction scenes get a tighter zoom box around the small bubble face,
    # since it's much smaller than half the source frame — sizing it to
    # CROP_W_HALF/CROP_H_HALF (like dual) would barely zoom in at all.
    FACE_BUBBLE_ZOOM = 3.0

    if scenes:
        for s in scenes:
            if s['mode'] not in ('dual', 'reaction'):
                continue

            if s['mode'] == 'dual':
                # Find first keyframe in this scene with two faces
                anchor = None
                for kf in sorted(face_data.keys()):
                    if kf < s['start'] or kf >= s['end']:
                        continue
                    faces = face_data[kf]
                    if len(faces) == 2:
                        cx0, cy0 = faces[0][0], faces[0][1]
                        cx1, cy1 = faces[1][0], faces[1][1]
                        # Face 0 lives in left half, face 1 in right half
                        box0 = _make_box(cx0, cy0, CROP_W_HALF, CROP_H_HALF, 0,        src_w // 2)
                        box1 = _make_box(cx1, cy1, CROP_W_HALF, CROP_H_HALF, src_w // 2, src_w)
                        anchor = {0: box0, 1: box1}
                        print(f"    📦  Anchor boxes set at frame {kf}: "
                              f"face0={box0[0]}-{box0[2]}px  face1={box1[0]}-{box1[2]}px")
                        break
                if anchor is None:
                    # No clean dual frame — use left/right midpoints as fallback
                    box0 = _make_box(src_w // 4,     src_h // 2, CROP_W_HALF, CROP_H_HALF, 0,          src_w // 2)
                    box1 = _make_box(3 * src_w // 4, src_h // 2, CROP_W_HALF, CROP_H_HALF, src_w // 2, src_w)
                    anchor = {0: box0, 1: box1}
                    print(f"    📦  Anchor boxes: no dual frame found, using midpoint fallback")

            else:   # reaction
                # Find first keyframe in this scene with a reaction-classified face
                anchor = None
                for kf in sorted(face_data.keys()):
                    if kf < s['start'] or kf >= s['end']:
                        continue
                    faces = face_data[kf]
                    if len(faces) == 1 and _is_reaction_face(faces[0], src_w, src_h):
                        cx, cy, fw, fh = faces[0]
                        # Face bubble: zoom tightly around the small face
                        face_box_w = min(src_w, int(fw * FACE_BUBBLE_ZOOM))
                        face_box_h = min(src_h, int(fh * FACE_BUBBLE_ZOOM))
                        face_box   = _make_box(cx, cy, face_box_w, face_box_h, 0, src_w)
                        # Content: center-crop of the full frame (the face bubble
                        # is a small overlay, so the frame center is the content)
                        content_box = _make_box(src_w // 2, src_h // 2, CROP_W_HALF, CROP_H_HALF, 0, src_w)
                        anchor = {0: face_box, 1: content_box}
                        print(f"    📦  Reaction anchor boxes set at frame {kf}: "
                              f"face={face_box[0]}-{face_box[2]}px  content=center-crop")
                        break
                if anchor is None:
                    # No clean reaction frame — fall back to a center-crop for both
                    box = _make_box(src_w // 2, src_h // 2, CROP_W_HALF, CROP_H_HALF, 0, src_w)
                    anchor = {0: box, 1: box}
                    print(f"    📦  Reaction anchor boxes: no reaction frame found, using center-crop fallback")

            anchor_boxes[s['start']] = anchor

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{OUT_W}x{OUT_H}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(video_path),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out_path),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    cap  = cv2.VideoCapture(str(video_path))

    frame_idx    = 0
    report_every = max(1, int(fps * 10))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        canvas = np.zeros((OUT_H, OUT_W, 3), dtype=np.uint8)

        # Determine mode for this frame
        kf   = (frame_idx // sample_every) * sample_every
        mode = scene_mode_per_frame.get(kf, 'single')

        if mode in ('dual', 'reaction'):
            # ── SPLIT SCREEN: fixed anchor box per region, never moves ──
            # 'dual'     → box0/box1 are the two people (top/bottom)
            # 'reaction' → box0 is the zoomed face bubble, box1 is the content
            box0 = box1 = None
            if scenes:
                for s in scenes:
                    if s['mode'] == mode and s['start'] <= frame_idx < s['end']:
                        anc = anchor_boxes.get(s['start'], {})
                        box0 = anc.get(0)
                        box1 = anc.get(1)
                        break
            # Fallback boxes
            if box0 is None:
                box0 = (0,           0, src_w // 2, src_h)
            if box1 is None:
                box1 = (src_w // 2, 0, src_w,      src_h)

            def _crop_box(frame, box):
                x1, y1, x2, y2 = box
                return frame[y1:y2, x1:x2]

            top_crop = _crop_box(frame, box0)
            bot_crop = _crop_box(frame, box1)

            canvas[0:HALF_H]     = cv2.resize(top_crop, (OUT_W, HALF_H))
            canvas[HALF_H:OUT_H] = cv2.resize(bot_crop, (OUT_W, HALF_H))

        else:
            # ── SINGLE FACE: track face 0 (or whoever is present), full frame ──
            n  = len(pos[0]['x'])
            cx = pos[0]['x'][frame_idx] if frame_idx < n else src_w // 2
            cy = pos[0]['y'][frame_idx] if frame_idx < n else src_h // 2
            crop_w_single = min(int(src_h * 9 / 16), src_w)
            crop = _crop_face(frame, cx, cy, crop_w_single, src_h, src_w, src_h)
            canvas = cv2.resize(crop, (OUT_W, OUT_H))

        proc.stdin.write(canvas.tobytes())

        if frame_idx % report_every == 0:
            secs = frame_idx / fps
            print(f"    \u23f1\ufe0f  {int(secs//60)}:{int(secs%60):02d} / {int(total_frames/fps//60)}:{int(total_frames/fps%60):02d}")

        frame_idx += 1

    proc.stdin.close()
    proc.wait()
    cap.release()
    return proc.returncode == 0


def _crop_face(frame, cx: int, cy: int, crop_w: int, crop_h: int, src_w: int, src_h: int):
    """Crop region centered on face, clamped to frame bounds."""
    x1 = max(0, min(cx - crop_w // 2, src_w - crop_w))
    x2 = x1 + crop_w
    y1 = max(0, min(cy - crop_h // 2, src_h - crop_h))
    y2 = y1 + crop_h
    return frame[y1:y2, x1:x2]


def _build_smooth_positions(face_data: dict, face_id: int, axis: str,
                             default: int, src_max: int, sample_every: int,
                             scene_boundaries: list = None) -> list:
    """
    Build a smooth per-frame position array for one face on one axis.
    Smoothing is applied within scenes only — never across scene boundaries.
    This prevents the camera from slowly panning into position after a cut.
    """
    import numpy as np
    try:
        from scipy.ndimage import gaussian_filter1d
        has_scipy = True
    except ImportError:
        has_scipy = False

    raw        = {}
    multi_face = set()   # keyframes where 2+ faces were seen — gaps here = don't interpolate
    max_frame  = max(face_data.keys()) if face_data else 0
    for frame_idx, faces in face_data.items():
        # For single-face tracking, only trust keyframes where exactly one face
        # was detected. Multi-face frames (cutaways, crowds) get skipped —
        # otherwise face_id=0 may refer to different people on consecutive
        # keyframes, causing the smoothing to oscillate between them.
        if len(faces) == 1 and face_id in faces:
            f = faces[face_id]
            raw[frame_idx] = f[0] if axis == 'x' else f[1]
        elif len(faces) >= 2:
            multi_face.add(frame_idx)

    if not raw:
        return [default] * (max_frame + sample_every + 1)

    total       = max_frame + sample_every + 1
    sorted_keys = sorted(raw.keys())
    result      = []

    # Find max gap between detections — if gap is short, interpolate smoothly.
    # If gap is long (>2s worth of frames), hold last position instead of
    # interpolating across it (which causes slow pans through empty space).
    max_gap_frames = int(2.0 / (sample_every / 25.0)) if sample_every else 50

    for i in range(total):
        before = [k for k in sorted_keys if k <= i]
        after  = [k for k in sorted_keys if k > i]
        if before and after:
            k1, k2 = before[-1], after[0]
            gap = k2 - k1

            # Clean cut across scene boundary — snap, don't pan
            if scene_boundaries:
                crossed = any(k1 < b <= i for b in scene_boundaries)
                if crossed:
                    result.append(raw.get(after[0], default))
                    continue

            if gap > max_gap_frames or any(k1 < m <= k2 for m in multi_face):
                # Large gap, or gap bridged by multi-face frames — hold position.
                # Interpolating here risks panning between two different people.
                if i - k1 <= gap // 2:
                    result.append(raw[k1])   # first half: hold previous position
                else:
                    result.append(raw[k2])   # second half: snap to next position
            else:
                # Short gap — smooth interpolation is fine
                t = (i - k1) / max(gap, 1)
                result.append(int(raw[k1] + t * (raw[k2] - raw[k1])))
        elif before:
            result.append(raw[before[-1]])
        elif after:
            result.append(raw[after[0]])
        else:
            result.append(default)

    # Smooth within scenes only
    if has_scipy and len(result) > 1:
        arr = np.array(result, dtype=float)
        if scene_boundaries:
            # Smooth each segment independently
            boundaries = sorted([0] + scene_boundaries + [total])
            for j in range(len(boundaries) - 1):
                seg_start = boundaries[j]
                seg_end   = min(boundaries[j + 1], len(arr))
                if seg_end - seg_start > 1:
                    arr[seg_start:seg_end] = gaussian_filter1d(arr[seg_start:seg_end], sigma=20)
            result = [int(v) for v in arr]
        else:
            result = [int(v) for v in gaussian_filter1d(arr, sigma=20)]

    return result


def _build_scene_mode_lookup(face_data: dict, sample_every: int,
                              src_w: int = None, src_h: int = None) -> dict:
    """
    Build a per-keyframe mode dict (dual/single/reaction) from face_data.
    This is the legacy fallback path used when `scenes` isn't passed in —
    it has no hysteresis smoothing, so it's prone to jump-cut flicker.
    Reaction classification requires src_w/src_h; if not provided, single-face
    frames are always classified as 'single' (known limitation of this path).
    """
    modes = {}
    for k in sorted(face_data.keys()):
        faces = face_data[k]
        if len(faces) == 2:
            modes[k] = 'dual'
        elif len(faces) == 1 and src_w and src_h and _is_reaction_face(faces[0], src_w, src_h):
            modes[k] = 'reaction'
        else:
            modes[k] = 'single'
    return modes
# Legacy alias kept for compatibility
def _crop_region(frame, cx, cy, crop_w, crop_h, src_w, src_h):
    return _crop_face(frame, cx, cy, crop_w, crop_h, src_w, src_h)


def _interpolate_face_positions(face_data, src_w, src_h, face_idx, sample_every, default, axis='x'):
    """Legacy wrapper — new code uses _build_smooth_positions with dict-based face_data."""
    # Convert old list-based face_data to new dict-based if needed
    new_face_data = {}
    for k, v in face_data.items():
        if isinstance(v, list):
            sorted_faces = sorted(v, key=lambda f: f[0])  # sort by X
            new_face_data[k] = {i: f for i, f in enumerate(sorted_faces[:2])}
        else:
            new_face_data[k] = v
    return _build_smooth_positions(new_face_data, face_idx, axis, default, src_w if axis=='x' else src_h, sample_every)


def _resolve_font(font_arg: str = None) -> str:
    """
    Return a font name/path to embed in the ASS style.
    Priority:
      1. --font CLI arg (if given and file exists)
      2. A Bebas Neue .ttf found anywhere on PATH-like locations
      3. A safe system fallback ("Arial" on Windows/Mac, "DejaVu Sans" on Linux)
    Returns just the font *name* (not path) because ASS uses names, not paths.
    The font must be installed / registered with the OS for ffmpeg libass to find it.
    If the user passes a raw .ttf path we copy it into the working dir and register
    its basename so libass can pick it up via the -fontsdir trick in burn_subtitles.
    """
    import platform

    if font_arg:
        p = Path(font_arg)
        if p.exists():
            return str(p)           # full path returned; burn_subtitles handles it
        # Treat as a font name (e.g. "Arial")
        return font_arg

    # System fallbacks
    system = platform.system()
    if system == "Windows":
        return "Arial"
    elif system == "Darwin":
        return "Helvetica Neue"
    else:
        return "DejaVu Sans"


def _ts_to_seconds(ts: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    ts = ts.replace(",", ".")
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + float(f"0.{ms}")


def _srt_to_ass(srt_path: Path, ass_path: Path, font: str = "Arial",
                scenes: list = None):
    """
    Convert SRT to ASS format with scene-aware subtitle positioning.

    Two styles are always written:
      - Default : bottom-center (alignment 2)  — used during single-face scenes
      - Split   : middle-center (alignment 5)  — used during split-screen scenes

    Each dialogue line is tagged with the correct style by looking up which
    scene covers its start timestamp.  If no scenes list is provided, all
    subtitles use the Default (bottom) style.

    `font` may be a font name or an absolute path to a .ttf file.
    """
    font_name = Path(font).stem if Path(font).suffix.lower() == ".ttf" else font

    # Build a sorted list of (start_sec, end_sec, mode) from scenes
    scene_ranges = []
    if scenes:
        for s in scenes:
            # scenes store frame numbers; convert to seconds via fps embedded in
            # the scene dict if available, otherwise we rely on caller to pass
            # pre-converted seconds.  render_split_screen stores fps separately,
            # so we accept both frames (int) and seconds (float) gracefully.
            scene_ranges.append(s)   # stored as-is; lookup below handles both

    def _style_for_time(start_sec: float) -> str:
        """Return 'Split' if this timestamp falls in a dual/split scene, else 'Default'."""
        if not scene_ranges:
            return "Default"
        for s in scene_ranges:
            # Scenes may store seconds directly or as frame-based values with an fps key
            s_start = s.get("start_sec", s.get("start", 0))
            s_end   = s.get("end_sec",   s.get("end",   float("inf")))
            if s_start <= start_sec < s_end:
                return "Split" if s.get("mode") in ("dual", "reaction") else "Default"
        return "Default"

    style_line = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 720\n"
        "PlayResY: 1280\n"
        "\n"
        "[V4+ Styles]\n"
        f"{style_line}"
        # Default style — bottom third (alignment 2), 427px margin from bottom (~1/3 up on 1280px)
        f"Style: Default,{font_name},35,&H00FFFFFF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,1,2,0,0,427,1\n"
        # Split style — middle-center (alignment 5), no margin
        f"Style: Split,{font_name},35,&H00FFFFFF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,1,5,0,0,0,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def srt_ts_to_ass(ts):
        ts = ts.replace(",", ".")
        h, m, rest = ts.split(":")
        s, ms = rest.split(".")
        return f"{int(h)}:{m}:{s}.{ms[:2]}"

    with open(srt_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    dialogue = []
    for block in raw.split("\n\n"):
        parts = block.strip().split("\n")
        if len(parts) < 3:
            continue
        times = parts[1].split(" --> ")
        if len(times) != 2:
            continue
        start_raw = times[0].strip()
        end_raw   = times[1].strip()
        start_sec = _ts_to_seconds(start_raw)
        style     = _style_for_time(start_sec)
        start_ts  = srt_ts_to_ass(start_raw)
        end_ts    = srt_ts_to_ass(end_raw)
        text      = " ".join(parts[2:]).replace("\n", "\\N")
        dialogue.append(f"Dialogue: 0,{start_ts},{end_ts},{style},,0,0,0,,{text}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(dialogue))


def burn_subtitles(video_path: Path, srt_path: Path, output_dir: Path,
                   font: str = "Arial", scenes: list = None) -> Path:
    """
    Burn subtitles using ASS format with scene-aware positioning.
    Subtitles automatically switch between bottom-center (single-face scenes)
    and middle-center (split-screen scenes) based on the scenes list.
    - font   -> font name or path to .ttf file
    - scenes -> list of scene dicts from analyse_faces() with 'start_sec'/'end_sec'/'mode'
    """
    import re

    safe_out = output_dir / "final_subtitled.mp4"

    if safe_out.exists():
        print(f"\u23e9  Subtitled video already exists \u279c {safe_out.name}")
        return safe_out

    has_split = scenes and any(s.get("mode") in ("dual", "reaction") for s in scenes)

    # Prefer karaoke ASS if per-word JSON is available (written by transcribe_video)
    words_json_path = srt_path.with_suffix(".words.json")
    ass_path = output_dir / "subs_temp.ass"

    if words_json_path.exists():
        mode_label = "karaoke" + (" + scene-aware" if has_split else "")
        print(f"\n\U0001f3ac  Burning subtitles ({mode_label}) \u2026")
        _write_karaoke_ass(words_json_path, ass_path, font=font, scenes=scenes)
    else:
        print(f"\n\U0001f3ac  Burning subtitles ({'scene-aware' if has_split else 'bottom-center'}) \u2026")
        _srt_to_ass(srt_path, ass_path, font=font, scenes=scenes)

    # Escape the ASS path for ffmpeg's -vf filter string.
    # On Windows/WSL, drive letters need special escaping: C:/ -> C\:/ 
    # re.sub backreference fix: use r"\1" (not r"\\1") so group 1 is inserted correctly.
    ass_str = str(ass_path).replace("\\", "/")
    ass_str = re.sub(r"^([A-Za-z]):/", r"\1\\:/", ass_str)

    # If the font is a .ttf path, tell libass where to find it via fontsdir
    vf_parts = []
    font_path = Path(font)
    if font_path.suffix.lower() == ".ttf" and font_path.exists():
        fonts_dir = str(font_path.parent).replace("\\", "/")
        fonts_dir = re.sub(r"^([A-Za-z]):/", r"\1\\:/", fonts_dir)
        vf_parts.append(f"ass='{ass_str}':fontsdir='{fonts_dir}'")
    else:
        vf_parts.append(f"ass='{ass_str}'")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", ",".join(vf_parts),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        str(safe_out),
    ]

    _run_ffmpeg(cmd)
    ass_path.unlink(missing_ok=True)
    print(f"\u2705  Subtitled video \u279c {safe_out.name}")
    return safe_out


def _sanitize_filename(text: str, max_len: int = 60) -> str:
    """
    Turn a chunk of transcript text into a safe filename fragment.
    Strips characters illegal on Windows filesystems (relevant since these
    scripts commonly run under WSL against /mnt/c) and collapses whitespace.
    """
    import re
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)          # illegal on Windows
    text = text.strip(" .,;:!?-\u2026")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].strip()
    return text or "clip"


_GROQ_LAST_CALL_TS = [0.0]     # module-level mutable box: last successful call time
_GROQ_MIN_INTERVAL = 2.2       # seconds between calls — keeps us safely under 30 req/min


def _groq_generate_title(text: str, max_words: int = 8) -> str:
    """
    Ask a free Groq-hosted LLM (llama-3.1-8b-instant) for a short, punchy
    TikTok-style title summarizing this clip's transcript — an actual
    summary rather than just the leading words.

    Returns "" on ANY failure (no API key set, network error, rate limit,
    bad response, etc.) so callers can fall back to the local heuristic
    title generator without ever crashing the pipeline over a title.

    Self-throttles to stay under Groq's free-tier ~30 requests/minute cap:
    blocks briefly before firing if called again too soon.
    """
    import os, time

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not text.strip():
        return ""

    try:
        import requests
    except ImportError:
        print("    \u26a0\ufe0f  'requests' not installed (pip install requests) \u2014 skipping LLM title")
        return ""

    elapsed = time.time() - _GROQ_LAST_CALL_TS[0]
    if elapsed < _GROQ_MIN_INTERVAL:
        time.sleep(_GROQ_MIN_INTERVAL - elapsed)

    prompt = (
        "You write short, punchy TikTok video titles summarizing transcript clips. "
        f"Write exactly ONE title, {max_words} words or fewer. "
        "No quotes, no hashtags, no emoji, no trailing punctuation, no preamble \u2014 "
        "output ONLY the title text itself.\n\n"
        f"Transcript:\n{text[:1500]}"
    )

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 30,
                "temperature": 0.5,
            },
            timeout=15,
        )
        _GROQ_LAST_CALL_TS[0] = time.time()

        if resp.status_code == 429:
            print("    \u26a0\ufe0f  Groq rate limit hit \u2014 falling back to local title")
            return ""
        resp.raise_for_status()

        title = resp.json()["choices"][0]["message"]["content"].strip()
        return _sanitize_filename(title) if title else ""
    except Exception as e:
        print(f"    \u26a0\ufe0f  Groq title generation failed ({e}) \u2014 falling back to local title")
        return ""


def generate_clip_title(text: str, max_words: int = 10, max_len: int = 60, use_llm: bool = True) -> str:
    """
    Derive a short, TikTok-style title from a clip's transcript text.

    If use_llm is True and GROQ_API_KEY is set in the environment, this asks
    a free Groq-hosted LLM for a real summary-style title. Otherwise (or if
    the API call fails for any reason) it falls back to a purely local
    heuristic: the leading words of the transcript, trimmed to a clean
    word/character boundary. Either way the result is sanitized for use as
    a filename — on TikTok, the uploaded file's name becomes the video's
    title/caption, so this is what viewers will see.
    """
    if not text:
        return "clip"

    if use_llm:
        llm_title = _groq_generate_title(text, max_words=max_words)
        if llm_title:
            return llm_title
    words = text.split()
    snippet = " ".join(words[:max_words])
    return _sanitize_filename(snippet, max_len=max_len)


def cut_into_clips(video_path: Path, clip_length: int, clips_dir: Path, all_words: list = None, use_llm_titles: bool = True):
    """
    Split the video into clips of `clip_length` seconds each.
    If all_words is provided, each clip is named after a short title derived
    from its own transcript slice (e.g. "01_this_is_the_hook.mp4") instead of
    the generic clip_001.mp4 — since that filename becomes the TikTok title
    on upload. Falls back to clip_NNN.mp4 when no transcript is available
    (e.g. --no-transcribe was passed).
    """
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Get video duration
    duration = _get_duration(video_path)
    print(f"\n✂️   Cutting into {clip_length}s clips  (total duration: {duration:.1f}s) …")

    num_clips = int(duration // clip_length) + (1 if duration % clip_length > 1 else 0)
    print(f"    Expected clips: {num_clips}")

    for i in range(num_clips):
        start = i * clip_length
        end   = min(start + clip_length, duration)

        if all_words:
            clip_words = _words_in_range(all_words, start, end)
            clip_text  = " ".join(w["word"] for w in clip_words)
            title      = generate_clip_title(clip_text, use_llm=use_llm_titles)
            clip_path  = clips_dir / f"{i+1:02d}_{title}.mp4"
        else:
            clip_path  = clips_dir / f"clip_{i+1:03d}.mp4"

        if clip_path.exists():
            print(f"    ⏩  {clip_path.name} already exists, skipping")
            continue

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(start),
            "-t", str(clip_length),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            str(clip_path),
        ]
        _run_ffmpeg(cmd, quiet=True)
        print(f"    ✅  {clip_path.name}  ({start}s – {min(start+clip_length, duration):.0f}s)")

    print(f"\n🎉  Done! {num_clips} clips saved to: {clips_dir}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_video_dims(video_path: Path):
    """Return (width, height) of video, or None on error."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info   = json.loads(result.stdout)
        w = info["streams"][0]["width"]
        h = info["streams"][0]["height"]
        return (w, h)
    except Exception:
        return None


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
        process = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        for line in process.stderr:
            # Only print progress lines to avoid spam
            if "time=" in line or "Error" in line or "error" in line.lower():
                print(f"    {line.rstrip()}")
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)


# ─── Hook finder ──────────────────────────────────────────────────────────────

# ── Signal word banks — tuned for news / political podcast content ────────────
# (Tucker Carlson, Candace Owens, news clips, political commentary)

# Named political/institutional entities — naming a target is itself a hook signal
_HOOK_NAMED_ENTITIES = [
    "biden", "trump", "obama", "harris", "pelosi", "schumer", "mcconnell",
    "desantis", "gavin newsom", "newsom", "aoc", "ocasio-cortez",
    "bernie", "sanders", "hillary", "clinton", "pence",
    "zelensky", "putin", "xi jinping", "macron", "trudeau",
    "the white house", "the fbi", "the cia", "the doj",
    "the fed", "the supreme court", "the pentagon", "nato",
    "mainstream media", "msm", "cnn", "msnbc", "fox news",
    "the new york times", "washington post", "the establishment",
    "the deep state", "big pharma", "wall street", "silicon valley",
    "the left", "the right", "the democrats", "the republicans",
    "the globalists", "the elites", "the regime",
    "erika kirk", "charlie kirk", "kirk",
    "epstein", "jeffrey epstein", "epstein island",
    "israel", "israeli", "hamas", "gaza", "netanyahu",
    "egypt", "egyptian",
    "the cartel", "cartels", "ms-13", "drug cartel",
]
# Conflict / attack language — high signal for political clips
_HOOK_CONFLICT = [
    "slammed", "blasted", "destroyed", "crushed", "attacked", "ripped",
    "fired back", "clapped back", "called out", "exposed", "dismantled",
    "torched", "eviscerated", "humiliated", "embarrassed", "obliterated",
    "shut down", "taken apart", "taken down",
    "goes after", "went after", "comes for", "came for",
    "confronted", "challenged", "accused", "blamed",
    "lied", "lied to", "caught lying", "caught on camera",
    "fact checked", "debunked", "proven wrong",
]
# Revelation / breaking news framing
_HOOK_REVELATION = [
    "just came out", "breaking", "just broke", "developing",
    "just admitted", "just confessed", "just announced", "just revealed",
    "admitted", "confessed", "revealed", "leaked", "obtained",
    "exclusive", "confirmed", "sources say", "according to sources",
    "we just learned", "it turns out",
    "the truth is", "the real story", "what really happened",
    "what they're not telling you", "what the media won't show",
    "they don't want you to see", "they don't want you to know",
    "suppressed", "censored", "banned", "deleted",
    "cover up", "cover-up", "covering up", "hiding",
]
# Stakes / consequence language
_HOOK_STAKES = [
    "threatens", "could end", "end of",
    "unprecedented", "historic", "crisis", "emergency",
    "disaster", "catastrophe", "collapse",
    "ban", "banned", "criminalize", "illegal",
    "arrest", "arrested", "indicted", "charged",
    "impeach", "impeached", "removed", "resign", "resigned",
    "declare war", "invasion", "attack on",
    "your rights", "freedom", "losing our",
    "they want to", "they're trying to", "they plan to",
    "agenda", "they need you to", "wake up",
]
# Strong assertion openers
_HOOK_ASSERTION = [
    "here's the thing", "here's what", "here's why",
    "the fact is", "the truth is", "the reality is",
    "let me be clear", "let me be honest", "let me tell you",
    "i'll tell you", "i'll say it", "i'll be direct",
    "nobody is saying", "no one is talking about",
    "what everyone is missing", "what no one will say",
    "this is important", "this matters", "pay attention",
    "think about this", "think about what",
    "the reason", "the real reason", "the actual reason",
    "this is what happens", "this is exactly",
    "you have to understand", "you need to understand",
    "understand this",
]
# Emotion / outrage
_HOOK_EMOTION = [
    "outrageous", "outraged", "disgusting", "disgraceful",
    "unacceptable", "shameful", "appalling", "horrifying",
    "terrifying", "dangerous", "radical", "extreme",
    "insane", "absurd", "ridiculous", "unbelievable",
    "corrupt", "corruption", "criminal",
    "evil", "sick", "twisted", "deranged", "delusional",
    "hypocrisy", "hypocrite", "hypocritical",
    "double standard", "rigged", "stolen", "fraud",
    "lie", "lies", "lying", "dishonest",
]
# Questions — weak signal for political content but still relevant
_HOOK_QUESTIONS = [
    "why is", "why are", "why does", "why did", "why would",
    "how is it", "how did", "how can",
    "what is going on", "what happened", "what does this mean",
    "when did", "who decided", "who is responsible",
    "do you think", "do you believe",
]
_HOOK_WEIGHTS = {
    "named_entity":  24,
    "conflict":      22,
    "revelation":    20,
    "stakes":        18,
    "assertion":     14,
    "emotion":       12,
    "number":         8,
    "question":       6,
}

# Individual keyword bonuses layered on top of the existing category weights.
# These bonuses are applied once per unique matching phrase in a hook window.
# The total keyword bonus is capped so one clip cannot win on keywords alone.
_HOOK_KEYWORD_WEIGHTS = {
    # Extremely strong
    "israel": 11,
    "jeffrey epstein": 18,
    "epstein": 16,
    "caught on camera": 15,
    "murdered": 14,
    "murder": 13,
    "torture": 14,
    "tortured": 14,
    "assassinated": 14,
    "cover-up": 13,
    "coverup": 13,

    # Strong institutions, regions, and high-stakes topics
    "middle east": 12,
    "cia": 12,
    "fbi": 11,
    "doj": 10,
    "department of justice": 10,
    "mossad": 12,
    "hamas": 11,
    "gaza": 11,
    "pentagon": 9,
    "white house": 8,
    "supreme court": 8,
    "congress": 7,
    "nato": 7,

    # Strong revelation / legal / conflict language
    "whistleblower": 11,
    "declassified": 10,
    "leaked": 10,
    "exclusive": 9,
    "breaking": 9,
    "confirmed": 8,
    "indicted": 9,
    "convicted": 9,
    "charged": 7,
    "arrested": 7,
    "raid": 7,
    "genocide": 12,
    "national security": 9,
    "human rights": 7,

    # Medium-strength controversy and ethics language
    "illegal": 7,
    "illegally": 7,
    "unethical": 6,
    "immoral": 5,
    "corruption": 7,
    "fraud": 7,
    "evidence": 6,
    "footage": 5,
    "recording": 5,
    "documents": 4,
    "files": 3,

    # Broader geopolitical terms
    "ukraine": 7,
    "russia": 7,
    "china": 7,
    "war": 5,
    "conflict": 4,
    "sanctions": 5,
    "crisis": 4,
    "emergency": 4,
}

_HOOK_KEYWORD_BONUS_CAP = 45

_HOOK_BOUNDARY_BONUS = 8
_HOOK_PACE_BONUS     = 6

# Sponsor / ad phrases — any window containing these is disqualified entirely.
# Checked across the full clip window (not just the opening hook), so a mid-clip
# ad read also poisons the clip. Score is forced to 0, preventing selection.
_AD_PHRASES = [
    # direct sponsor callouts
    "this video is sponsored", "this video is brought to you",
    "today's sponsor", "today's video is sponsored",
    "brought to you by", "paid partnership", "paid promotion",
    "in partnership with", "working with", "thanks to our sponsor",
    "thank our sponsor", "special thanks to",
    # promo actions
    "use my code", "use code", "promo code", "discount code",
    "coupon code", "affiliate link", "link in the description",
    "link in bio", "check the description", "check out the link",
    "use the link below", "swipe up",
    # subscription / merch plugs
    "check out their website", "visit their site", "go to",
    "download the app", "sign up for free", "free trial",
    "first month free", "percent off", "% off", "dollars off",
    # creator economy ad reads
    "nordvpn", "expressvpn", "surfshark", "squarespace", "wix",
    "skillshare", "brilliant", "curiositystream", "nebula",
    "manscaped", "dollar shave", "hello fresh", "factor meals",
    "athletic greens", "ag1", "betterhelp", "netsuite",
    "hubspot", "shopify", "raycon", "ridge wallet",
    "established titles", "ground news",
]


def _hook_contains(text: str, phrases: list) -> list:
    t = text.lower()
    return [p for p in phrases if p in t]


def _is_ad_window(words: list, start_sec: float, clip_length: float) -> bool:
    """
    Return True if the clip window [start_sec, start_sec+clip_length] contains
    any sponsor/ad phrase.  Checks the full clip, not just the opening window,
    so mid-clip ad reads also disqualify the candidate.
    """
    clip_words = [w for w in words
                  if w["start"] >= start_sec
                  and w["start"] < start_sec + clip_length]
    text = " ".join(w["word"] for w in clip_words).lower()
    return any(phrase in text for phrase in _AD_PHRASES)



def _hook_weighted_keyword_hits(text: str) -> tuple[list, int]:
    """
    Return unique weighted keyword matches and their capped bonus.

    Longer phrases are checked first so "Jeffrey Epstein" is not also counted
    as a second independent "Epstein" hit from the same wording.
    """
    import re as _re

    lowered = text.lower()
    occupied = []
    matches = []

    for phrase, weight in sorted(
        _HOOK_KEYWORD_WEIGHTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = r"(?<!\w)" + _re.escape(phrase) + r"(?!\w)"
        match = _re.search(pattern, lowered)
        if not match:
            continue

        span = match.span()
        overlaps_existing = any(
            span[0] < end and span[1] > start
            for start, end in occupied
        )
        if overlaps_existing:
            continue

        occupied.append(span)
        matches.append((phrase, weight))

    total = min(
        _HOOK_KEYWORD_BONUS_CAP,
        sum(weight for _, weight in matches),
    )
    return matches, total


def _hook_count_numbers(text: str) -> int:
    import re as _re
    written = {
        "zero","one","two","three","four","five","six","seven","eight",
        "nine","ten","eleven","twelve","thirteen","fourteen","fifteen",
        "sixteen","seventeen","eighteen","nineteen","twenty","hundred",
        "thousand","million","billion","percent",
    }
    digit_count  = len(_re.findall(r"\b\d[\d,\.]*\b", text))
    word_count   = sum(1 for w in _re.findall(r"\b\w+\b", text.lower()) if w in written)
    return digit_count + word_count


def _hook_score_chunk(chunk_words: list, text: str, avg_wps: float) -> dict:
    raw = {}
    signals = {}

    # Named entity — naming a politician/institution is the primary political hook signal
    ne_hits = _hook_contains(text, _HOOK_NAMED_ENTITIES)
    if ne_hits:
        signals["named_entity"] = ne_hits[:2]
        raw["named_entity"] = _HOOK_WEIGHTS["named_entity"]
    else:
        raw["named_entity"] = 0

    # Conflict / attack language
    cf_hits = _hook_contains(text, _HOOK_CONFLICT)
    if cf_hits:
        signals["conflict"] = cf_hits[:2]
        raw["conflict"] = _HOOK_WEIGHTS["conflict"]
    else:
        raw["conflict"] = 0

    # Revelation / breaking framing
    rv_hits = _hook_contains(text, _HOOK_REVELATION)
    if rv_hits:
        signals["revelation"] = rv_hits[:2]
        raw["revelation"] = _HOOK_WEIGHTS["revelation"]
    else:
        raw["revelation"] = 0

    # Stakes / consequence language
    sk_hits = _hook_contains(text, _HOOK_STAKES)
    if sk_hits:
        signals["stakes"] = sk_hits[:2]
        raw["stakes"] = _HOOK_WEIGHTS["stakes"]
    else:
        raw["stakes"] = 0

    # Strong assertion opener
    as_hits = _hook_contains(text, _HOOK_ASSERTION)
    if as_hits:
        signals["assertion"] = as_hits[:2]
        raw["assertion"] = _HOOK_WEIGHTS["assertion"]
    else:
        raw["assertion"] = 0

    # Emotion / outrage language
    em_hits = _hook_contains(text, _HOOK_EMOTION)
    if em_hits:
        signals["emotion"] = em_hits[:2]
        raw["emotion"] = _HOOK_WEIGHTS["emotion"]
    else:
        raw["emotion"] = 0

    # Number / stat (polling numbers, dates, dollar amounts)
    n = _hook_count_numbers(text)
    if n >= 2:
        signals["number"] = [f"{n} numbers/stats"]
        raw["number"] = _HOOK_WEIGHTS["number"]
    elif n == 1:
        signals["number"] = ["1 number/stat"]
        raw["number"] = int(_HOOK_WEIGHTS["number"] * 0.6)
    else:
        raw["number"] = 0

    # Question — weak signal for political content
    q_hits = _hook_contains(text, _HOOK_QUESTIONS)
    if q_hits or "?" in text:
        signals["question"] = q_hits[:1] or ["?"]
        raw["question"] = _HOOK_WEIGHTS["question"]
    else:
        raw["question"] = 0

    # Stacking bonus: multiple categories firing together = much stronger hook
    categories_hit = sum(1 for v in raw.values() if v > 0)
    stack_bonus = 0
    if categories_hit >= 4:
        stack_bonus = 15
    elif categories_hit >= 3:
        stack_bonus = 8
    elif categories_hit >= 2:
        stack_bonus = 3

    # Boundary bonus (first word capitalised → likely sentence start)
    boundary = _HOOK_BOUNDARY_BONUS if chunk_words[0]["word"].strip()[:1].isupper() else 0

    # Pace spike bonus
    duration = chunk_words[-1]["end"] - chunk_words[0]["start"]
    chunk_wps = len(chunk_words) / duration if duration > 0 else 0
    pace_bonus = _HOOK_PACE_BONUS if (avg_wps > 0 and chunk_wps > avg_wps * 1.35) else 0
    if pace_bonus:
        signals["pace_spike"] = [f"{chunk_wps:.1f} w/s vs avg {avg_wps:.1f}"]

    # Individual keyword layer. This supplements category scoring rather than
    # replacing it, so an important proper noun can meaningfully distinguish
    # otherwise similar candidates.
    keyword_hits, keyword_bonus = _hook_weighted_keyword_hits(text)
    if keyword_hits:
        signals["weighted_keywords"] = [
            f"{phrase} (+{weight})"
            for phrase, weight in keyword_hits[:5]
        ]

    score = min(
        100,
        round(
            sum(raw.values())
            + stack_bonus
            + boundary
            + pace_bonus
            + keyword_bonus
        ),
    )
    return {
        "score": score,
        "signals": signals,
        "keyword_bonus": keyword_bonus,
    }


def _find_sentence_boundary(words: list, hook_word_idx: int,
                             max_lookback_sec: float = 8.0,
                             pause_threshold: float = 0.4) -> int:
    """
    Walk backwards from `hook_word_idx` to find the start of the sentence
    or thought that contains the hook phrase.

    A boundary is detected when:
      - The gap between word[n-1].end and word[n].start exceeds pause_threshold
        (speaker paused — natural sentence break in speech)
      - word[n-1] ends with sentence-ending punctuation: . ? !
      - We've walked back more than max_lookback_sec from the hook word

    Returns the index of the first word of the containing sentence.
    Falls back to hook_word_idx if no boundary is found within the lookback window.
    """
    if hook_word_idx <= 0:
        return 0

    hook_time = words[hook_word_idx]["start"]
    cutoff    = hook_time - max_lookback_sec

    for idx in range(hook_word_idx, 0, -1):
        prev_word = words[idx - 1]
        curr_word = words[idx]

        # Hard stop: don't look back further than max_lookback_sec
        if curr_word["start"] < cutoff:
            return idx

        # Pause boundary: gap between end of previous word and start of this one
        gap = curr_word["start"] - prev_word["end"]
        if gap >= pause_threshold:
            return idx

        # Punctuation boundary: previous word ends a sentence
        prev_text = prev_word["word"].strip()
        if prev_text and prev_text[-1] in ".?!":
            return idx

    return 0


def _score_clip_body(words: list, start_sec: float, scan_sec: float,
                     avg_wps: float) -> dict:
    """
    Score the body of a clip for signal density across the first `scan_sec`.
    Slides 30-word windows across that range and averages their hook scores.
    Returns body_score (0-100) and all signal types found.
    """
    body_words = [w for w in words
                  if w["start"] >= start_sec
                  and w["start"] < start_sec + scan_sec]
    if not body_words:
        return {"body_score": 0, "body_signals": {}, "unique_categories": 0}

    all_signals: dict = {}
    scores = []
    for j in range(0, len(body_words), 10):
        chunk = body_words[j : j + 30]
        if not chunk:
            break
        text   = " ".join(w["word"] for w in chunk)
        result = _hook_score_chunk(chunk, text, avg_wps)
        if result["score"] > 0:
            scores.append(result["score"])
            for k, v in result["signals"].items():
                if k not in all_signals:
                    all_signals[k] = v

    body_score = min(100, round(sum(scores) / len(scores))) if scores else 0
    return {"body_score": body_score, "body_signals": all_signals,
            "unique_categories": len(all_signals)}


# ─── Improved hook quality scoring ───────────────────────────────────────────

_CONTEXT_DEPENDENT_OPENERS = (
    "and ", "but ", "so ", "because ", "then ", "also ",
    "like i said", "as i said", "as i mentioned", "as we discussed",
    "he said", "she said", "they said", "it was", "this was",
    "that was", "they were", "the other thing", "another thing",
)

_VAGUE_OPENING_WORDS = {
    "he", "she", "they", "it", "this", "that", "these", "those",
    "there", "him", "her", "them", "his", "their",
}

_PAYOFF_PHRASES = [
    "it turned out", "turns out", "the result was", "the reason was",
    "the truth was", "what happened next", "and that is when",
    "and that's when", "then i realized", "then we realized",
    "we discovered", "they discovered", "we found out", "i found out",
    "in the end", "eventually", "finally", "which means",
    "that means", "because of that", "as a result", "the answer is",
    "here's the answer", "the conclusion", "the outcome",
    "everyone survived", "no one survived", "was convicted", "was arrested",
    "was fired", "was removed", "won the case", "lost the case",
]

_UNFINISHED_ENDINGS = (
    "and", "but", "because", "so", "then", "or", "if", "when", "while",
    "which", "that", "to", "of", "with", "for", "from", "about",
    "the", "a", "an", "this", "these", "those", "like",
)


def _words_in_range(words: list, start_sec: float, end_sec: float) -> list:
    """Return transcript words whose start time falls inside a time range."""
    return [w for w in words if start_sec <= w["start"] < end_sec]


def _score_standalone_opening(clip_words: list) -> dict:
    """Estimate whether a clip opening makes sense without earlier context."""
    if not clip_words:
        return {"score": 0, "reasons": ["no transcript"]}

    opening_words = clip_words[:24]
    opening = " ".join(w["word"] for w in opening_words).strip().lower()
    tokens = [w["word"].strip(".,!?;:\"'()[]{}").lower() for w in opening_words]

    score = 100
    reasons = []

    for phrase in _CONTEXT_DEPENDENT_OPENERS:
        if opening.startswith(phrase):
            score -= 24
            reasons.append(f"context opener: {phrase.strip()}")
            break

    vague_count = sum(token in _VAGUE_OPENING_WORDS for token in tokens[:12])
    if vague_count >= 4:
        score -= 22
        reasons.append("many vague references")
    elif vague_count >= 2:
        score -= 10
        reasons.append("some vague references")

    # A proper noun, number, question, or explicit assertion adds immediate context.
    original_tokens = [w["word"].strip() for w in opening_words[:12]]
    has_named_context = any(t[:1].isupper() for t in original_tokens[1:] if t)
    has_number = _hook_count_numbers(opening) > 0
    has_question = "?" in opening or bool(_hook_contains(opening, _HOOK_QUESTIONS))
    has_assertion = bool(_hook_contains(opening, _HOOK_ASSERTION))
    if has_named_context or has_number or has_question or has_assertion:
        score += 8

    # Very short fragments are usually poor standalone openings.
    if len(tokens) < 8:
        score -= 15
        reasons.append("opening fragment is very short")

    return {"score": max(0, min(100, round(score))), "reasons": reasons}


def _score_payoff(clip_words: list, avg_wps: float) -> dict:
    """Score whether the second half contains a reveal, answer, or consequence."""
    if not clip_words:
        return {"score": 0, "signals": {}}

    midpoint = len(clip_words) // 2
    latter = clip_words[midpoint:]
    latter_text = " ".join(w["word"] for w in latter)
    full_text = " ".join(w["word"] for w in clip_words)

    score = 0
    signals = {}

    payoff_hits = _hook_contains(latter_text, _PAYOFF_PHRASES)
    if payoff_hits:
        score += min(48, 26 + 8 * (len(payoff_hits) - 1))
        signals["payoff_phrase"] = payoff_hits[:3]

    # Reward consequences/revelations in the latter half specifically.
    latter_result = _hook_score_chunk(latter[:40] or latter, latter_text, avg_wps)
    high_value = {"revelation", "stakes", "conflict", "number"}
    latter_categories = high_value.intersection(latter_result["signals"])
    if latter_categories:
        score += 12 * len(latter_categories)
        signals["late_signals"] = sorted(latter_categories)

    # Reward a question in the first third that receives declarative content later.
    first_third = clip_words[:max(1, len(clip_words) // 3)]
    first_text = " ".join(w["word"] for w in first_third)
    if ("?" in first_text or _hook_contains(first_text, _HOOK_QUESTIONS)) and len(latter) >= 15:
        score += 14
        signals["question_answer_shape"] = ["question followed by body"]

    # Reward concrete detail in the payoff, but cap it so number-heavy sections do not dominate.
    number_count = _hook_count_numbers(latter_text)
    if number_count:
        score += min(12, number_count * 4)

    # Penalize clips that repeatedly promise a reveal but never provide one.
    promises = _hook_contains(full_text, ["coming up", "later i'll", "wait until", "stay tuned"])
    if promises and not payoff_hits:
        score -= 20
        signals["unfulfilled_promise"] = promises[:2]

    return {"score": max(0, min(100, round(score))), "signals": signals}


def _find_clean_clip_end(words: list, start_sec: float, target_length: float,
                         min_fraction: float = 0.72,
                         extension_sec: float = 8.0,
                         pause_threshold: float = 0.45) -> float:
    """
    Pick a natural ending near the requested duration.
    Searches from 72% of target length through target+8 seconds and prefers
    sentence punctuation or a meaningful pause.
    """
    earliest = start_sec + target_length * min_fraction
    target = start_sec + target_length
    latest = target + extension_sec
    nearby = [w for w in words if earliest <= w["end"] <= latest]
    if not nearby:
        return min(target, words[-1]["end"])

    candidates = []
    for idx, word in enumerate(words[:-1]):
        if word not in nearby:
            continue
        next_word = words[idx + 1]
        gap = next_word["start"] - word["end"]
        token = word["word"].strip()
        punctuation = bool(token and token[-1] in ".?!")
        pause = gap >= pause_threshold
        if punctuation or pause:
            distance = abs(word["end"] - target)
            quality_bonus = 2.0 if punctuation else 0.8
            candidates.append((distance - quality_bonus, word["end"]))

    if candidates:
        candidates.sort(key=lambda item: item[0])
        return min(candidates[0][1], words[-1]["end"])
    return min(target, words[-1]["end"])


def _score_ending(clip_words: list, end_sec: float, all_words: list) -> dict:
    """Score whether the chosen clip ending feels complete rather than abrupt."""
    if not clip_words:
        return {"score": 0, "reasons": ["no transcript"]}

    last = clip_words[-1]
    token = last["word"].strip()
    clean_punctuation = bool(token and token[-1] in ".?!")
    normalized = token.strip(".,!?;:\"'()[]{}").lower()

    score = 45
    reasons = []
    if clean_punctuation:
        score += 40
        reasons.append("ends on sentence punctuation")

    # Find the next transcript word to inspect the pause after the ending.
    next_words = [w for w in all_words if w["start"] >= last["end"] and w is not last]
    if next_words:
        gap = next_words[0]["start"] - last["end"]
        if gap >= 0.65:
            score += 20
            reasons.append("ends before a strong pause")
        elif gap >= 0.35:
            score += 10
            reasons.append("ends before a pause")

    if normalized in _UNFINISHED_ENDINGS:
        score -= 40
        reasons.append(f"ends on unfinished word: {normalized}")

    # If the final transcript word is materially before the video cut, silence is a clean buffer.
    if end_sec - last["end"] >= 0.35:
        score += 8

    return {"score": max(0, min(100, round(score))), "reasons": reasons}


def _candidate_tokens(candidate: dict) -> set:
    """Normalized token set used to suppress semantically repetitive candidates."""
    import re as _re
    text = candidate.get("clip_text", "").lower()
    stop = {
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on",
        "for", "is", "are", "was", "were", "it", "that", "this", "with",
        "you", "i", "we", "they", "he", "she", "as", "at", "be", "have",
        "has", "had", "do", "does", "did", "so", "not",
    }
    return {t for t in _re.findall(r"[a-z0-9']+", text) if len(t) > 2 and t not in stop}


def _text_similarity(a: dict, b: dict) -> float:
    """Fast Jaccard similarity; dependency-free duplicate-topic suppression."""
    ta = a.get("token_set") or _candidate_tokens(a)
    tb = b.get("token_set") or _candidate_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_hook_clips(words: list, n_hooks: int, clip_length: int,
                    window_words: int = 30, step_words: int = 8,
                    max_lookback_sec: float = 8.0,
                    body_scan_sec: float = 60.0,
                    face_timestamps: set = None,
                    similarity_limit: float = 0.58) -> list:
    """
    Two-stage, dependency-free hook ranker.

    Stage 1 generates many candidates using the original high-interest signal
    detector. Stage 2 reranks each complete clip using:

        opening hook       35%
        sustained body     15%
        payoff             25%
        standalone clarity 15%
        clean ending       10%

    It also chooses a natural ending near the requested duration and suppresses
    both time-overlapping and topic-duplicate clips.
    """
    if not words or n_hooks <= 0:
        return []

    total_duration = words[-1]["end"]
    total_words = len(words)
    total_dur = words[-1]["end"] - words[0]["start"]
    avg_wps = total_words / total_dur if total_dur > 0 else 3.0

    candidates = []
    i = 0
    while i < total_words:
        chunk = words[i:i + window_words]
        if not chunk:
            break
        if chunk[0]["start"] > total_duration - clip_length * 0.5:
            break

        text = " ".join(w["word"] for w in chunk)

        if face_timestamps is not None:
            window_start = chunk[0]["start"]
            window_end = window_start + 15.0
            has_face = any(window_start - 1.0 <= t <= window_end for t in face_timestamps)
            if not has_face:
                i += step_words
                continue

        result = _hook_score_chunk(chunk, text, avg_wps)
        if result["score"] <= 0:
            i += step_words
            continue

        trigger_word_idx = i
        for _, hits in result["signals"].items():
            if not hits or not isinstance(hits[0], str):
                continue
            phrase = hits[0].lower()
            if "w/s" in phrase or "number" in phrase:
                continue
            phrase_pos = text.lower().find(phrase)
            if phrase_pos >= 0:
                words_before = len(text.lower()[:phrase_pos].split())
                trigger_word_idx = min(i + words_before, i + len(chunk) - 1)
                break

        boundary_idx = _find_sentence_boundary(
            words, trigger_word_idx, max_lookback_sec=max_lookback_sec)
        actual_start = words[boundary_idx]["start"]

        if _is_ad_window(words, actual_start, clip_length + 8.0):
            i += step_words
            continue

        actual_end = _find_clean_clip_end(words, actual_start, clip_length)
        clip_words = _words_in_range(words, actual_start, actual_end + 0.01)
        if len(clip_words) < max(20, int(avg_wps * clip_length * 0.35)):
            i += step_words
            continue

        body = _score_clip_body(
            words, actual_start, min(body_scan_sec, actual_end - actual_start), avg_wps)
        standalone = _score_standalone_opening(clip_words)
        payoff = _score_payoff(clip_words, avg_wps)
        ending = _score_ending(clip_words, actual_end, words)

        hook_score = result["score"]
        body_score = body["body_score"]
        final_score = round(
            hook_score * 0.35
            + body_score * 0.15
            + payoff["score"] * 0.25
            + standalone["score"] * 0.15
            + ending["score"] * 0.10
        )
        final_score = max(0, min(100, final_score))

        preview_words = words[boundary_idx:boundary_idx + 18]
        preview = " ".join(w["word"] for w in preview_words)
        if len(clip_words) > len(preview_words):
            preview += "…"

        clip_text = " ".join(w["word"] for w in clip_words)
        candidate = {
            "start_sec": round(actual_start, 2),
            "end_sec": round(min(actual_end, total_duration), 2),
            "duration_sec": round(min(actual_end, total_duration) - actual_start, 2),
            "timestamp": _seconds_to_hhmmss(actual_start),
            "hook_phrase_sec": round(words[trigger_word_idx]["start"], 2),
            "score": final_score,
            "hook_score": hook_score,
            "body_score": body_score,
            "payoff_score": payoff["score"],
            "standalone_score": standalone["score"],
            "ending_score": ending["score"],
            "signals": result["signals"],
            "body_signals": body["body_signals"],
            "payoff_signals": payoff["signals"],
            "standalone_reasons": standalone["reasons"],
            "ending_reasons": ending["reasons"],
            "hook_preview": preview,
            "clip_text": clip_text,
        }
        candidate["token_set"] = _candidate_tokens(candidate)
        candidates.append(candidate)
        i += step_words

    # Keep a broader shortlist before final diversity selection. This preserves
    # high-quality alternatives when the top candidates overlap or repeat topics.
    candidates.sort(
        key=lambda x: (x["score"], x["payoff_score"], x["standalone_score"]),
        reverse=True,
    )
    shortlist = candidates[:max(n_hooks * 10, 40)]

    kept = []
    for candidate in shortlist:
        overlaps = any(
            existing["start_sec"] < candidate["end_sec"]
            and candidate["start_sec"] < existing["end_sec"]
            for existing in kept
        )
        if overlaps:
            continue

        too_similar = any(
            _text_similarity(candidate, existing) >= similarity_limit
            for existing in kept
        )
        if too_similar:
            continue

        candidate.pop("token_set", None)
        candidate.pop("clip_text", None)
        kept.append(candidate)
        if len(kept) >= n_hooks:
            break

    return kept

def _seconds_to_hhmmss(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sc = int(s % 60)
    return f"{h:02d}:{m:02d}:{sc:02d}"


def cut_hook_clips(video_path: Path, hooks: list, clip_length: int, clips_dir: Path):
    """
    Cut one clip per hook starting point.
    Files are named: hook_01_score82_0m14s.mp4, etc.
    """
    clips_dir.mkdir(parents=True, exist_ok=True)
    duration = _get_duration(video_path)

    print(f"\n✂️   Cutting {len(hooks)} hook clip(s) × {clip_length}s …")

    _SIGNAL_ICONS = {
        "named_entity": "🎯", "conflict":  "⚔️",  "revelation": "💥",
        "stakes":       "⚠️",  "assertion": "📢",  "emotion":    "🔥",
        "number":       "🔢",  "question":  "❓",  "pace_spike": "🏃",
    }

    for i, hook in enumerate(hooks, 1):
        start   = hook["start_sec"]
        end     = min(start + clip_length, duration)
        actual  = round(end - start, 1)
        mins    = int(start // 60)
        secs    = int(start % 60)
        icons   = "".join(_SIGNAL_ICONS.get(k, "") for k in hook["signals"])
        name    = f"hook_{i:02d}_score{hook['score']}_{mins}m{secs:02d}s.mp4"
        out     = clips_dir / name

        if out.exists():
            print(f"    ⏩  {name} already exists, skipping")
            continue

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(start),
            "-t", str(actual),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            str(out),
        ]
        _run_ffmpeg(cmd, quiet=True)
        print(f"    ✅  {name}  {icons}  score={hook['score']}  "
              f"({hook['timestamp']} → +{clip_length}s)")

    print(f"\n🎉  {len(hooks)} hook clip(s) saved to: {clips_dir}")


def _print_hook_summary(hooks: list):
    """Print a ranked summary table of detected hooks."""
    _ICONS = {
        "named_entity": "🎯", "conflict":  "⚔️",  "revelation": "💥",
        "stakes":       "⚠️",  "assertion": "📢",  "emotion":    "🔥",
        "number":       "🔢",  "question":  "❓",  "pace_spike": "🏃",
    }
    print(f"\n{'═'*62}")
    print(f"  🪝  Hook Analysis — {len(hooks)} candidate(s) found")
    print(f"{'═'*62}")
    for i, h in enumerate(hooks, 1):
        bar        = "█" * round(h["score"] / 5) + "░" * (20 - round(h["score"] / 5))
        hook_score = h.get("hook_score", h["score"])
        body_score = h.get("body_score", 0)
        icons      = " ".join(_ICONS.get(k, k) for k in h["signals"])
        body_icons = " ".join(_ICONS.get(k, k) for k in h.get("body_signals", {})
                              if k not in h["signals"])
        print(f"  #{i}  [{bar}] {h['score']:>3}/100  @  {h['timestamp']}")
        print(f"       \"{h['hook_preview']}\"")
        payoff     = h.get("payoff_score", 0)
        standalone = h.get("standalone_score", 0)
        ending     = h.get("ending_score", 0)
        duration   = h.get("duration_sec", h.get("end_sec", 0) - h.get("start_sec", 0))
        print(f"       Hook {hook_score:>3}  Body {body_score:>3}  Payoff {payoff:>3}  "
              f"Standalone {standalone:>3}  Ending {ending:>3}")
        print(f"       Duration: {duration:.1f}s")
        print(f"       Open : {icons if icons else '(none)'}")
        if body_icons:
            print(f"       Body : {body_icons}")
        print()
    print(f"{'═'*62}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download YouTube video → transcribe → burn subs → cut into clips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="YouTube video URL, or path to a local video file")
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
        help="Keep the original downloaded video file after processing",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Clear working/intermediate files before running so everything regenerates fresh. The clips folder is always preserved.",
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
        "--hooks", type=int, default=0, metavar="N",
        help=(
            "Find the N highest-scoring hook starting points and cut one clip per hook. "
            "Replaces uniform clip cutting. Example: --hooks 5"
        ),
    )
    parser.add_argument(
        "--hook-clip-length", type=int, default=120,
        help="Length of each hook clip in seconds (default: 120). Used only with --hooks.",
    )
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
    args = parser.parse_args()

    # ── Scene-type gating ──
    # If none of --single/--dual/--reaction are passed, search for all three (current
    # default behaviour). If one or more are passed, only those scene types are
    # detected — everything else falls back to a plain single-person crop.
    _requested_modes = {
        name for name, flag in
        (("single", args.single), ("dual", args.dual), ("reaction", args.reaction))
        if flag
    }
    allowed_modes = _requested_modes if _requested_modes else {"single", "dual", "reaction"}

    # ── Setup ──
    import shutil as _shutil
    from datetime import datetime as _dt
    check_dependencies()

    base_dir   = Path(args.output).resolve()
    # Each run gets its own timestamped working folder so --fresh never
    # touches clips from previous runs
    timestamp  = _dt.now().strftime("%Y%m%d_%H%M%S")
    output_dir = base_dir / timestamp
    clips_dir  = base_dir / "clips" / timestamp

    if args.fresh and base_dir.exists():
        print(f"\n🗑️   Clearing working files (clips folder preserved): {base_dir}")
        for item in base_dir.iterdir():
            # Never touch the clips folder — it holds output from all previous runs
            if item.name == "clips":
                continue
            if item.is_dir():
                _shutil.rmtree(item)
            else:
                item.unlink(missing_ok=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  YouTube Clip Processor")
    print("=" * 60)
    print(f"  Source       : {args.url}")
    print(f"  Output dir   : {output_dir}")
    if args.hooks:
        print(f"  Hook mode    : {args.hooks} hooks × {args.hook_clip_length}s each")
    else:
        print(f"  Clip length  : {args.clip_length}s")
    print(f"  Whisper model: {args.whisper_model}")
    print(f"  Vertical 9:16: {not args.no_vertical}")
    print(f"  Burn subs    : {not args.no_burn_subs}")
    print(f"  Words/line   : {args.words_per_line}")
    print(f"  Sub delay    : {args.subtitle_delay}s")
    print(f"  Font         : {args.font or '(system default)'}")
    print("=" * 60)

    # ── Resolve font (after arg parsing) ──
    resolved_font = _resolve_font(args.font)

    # ── Step 1: Download or use local file ──
    local_path = Path(args.url).expanduser()
    if local_path.exists() and local_path.is_file():
        # Local file — copy/sanitize into the working dir so derived filenames are clean
        clean_stem = _sanitize_filename(local_path.stem)
        video_path = output_dir / (clean_stem + ".mp4")
        if not video_path.exists():
            import shutil as _shutil2
            print(f"\n📂  Using local file: {local_path.name}")
            _shutil2.copy2(local_path, video_path)
            print(f"✅  Copied → {video_path.name}")
        else:
            print(f"\n⏩  Local file already in workdir → {video_path.name}")
    else:
        video_path = download_video(args.url, output_dir)

    # ── Step 1b: Trim if --start / --end specified ──
    if args.start or args.end:
        video_path = trim_video(video_path, output_dir, args.start, args.end)

    if args.hooks:
        # ── HOOK MODE: transcribe first, score, then process only matched segments ──

        if args.no_transcribe:
            print("⚠️  --hooks requires transcription. Ignoring --no-transcribe.")

        # Step 2 (hook): transcribe full audio only — no video processing yet
        all_words = transcribe_audio_only(video_path, args.whisper_model, output_dir)

        # Step 2b (hook): lightweight face sampling pass — used to gate hook
        # selection so only moments with a face on screen can become clip starts
        face_timestamps = set()
        if not args.no_vertical:
            face_timestamps = sample_face_timestamps(video_path, sample_every_sec=1.0)

        # Step 3 (hook): score and find top N hook starting points
        hooks = find_hook_clips(
            all_words,
            n_hooks          = args.hooks,
            clip_length      = args.hook_clip_length,
            face_timestamps  = face_timestamps if face_timestamps else None,
        )
        _print_hook_summary(hooks)

        if not hooks:
            print("⚠️  No hook candidates found. Try --hooks with a longer video,")
            print("    or run without --hooks for uniform clip cutting.")
        else:
            # Step 4 (hook): for each hook, run the full pipeline on that segment only
            _SIGNAL_ICONS = {
                "named_entity": "🎯", "conflict":  "⚔️",  "revelation": "💥",
                "stakes":       "⚠️",  "assertion": "📢",  "emotion":    "🔥",
                "number":       "🔢",  "question":  "❓",  "pace_spike": "🏃",
            }
            for i, hook in enumerate(hooks, 1):
                icons    = "".join(_SIGNAL_ICONS.get(k, "") for k in hook["signals"])
                mins     = int(hook["start_sec"] // 60)
                secs_val = int(hook["start_sec"] % 60)
                title    = generate_clip_title(hook.get("clip_text") or hook.get("hook_preview", ""),
                                               use_llm=not args.no_llm_titles)
                clip_name = f"{i:02d}_{title}.mp4"
                clip_path = clips_dir / clip_name
                seg_dir   = output_dir / f"seg_{i:02d}"

                if clip_path.exists():
                    print(f"\n⏩  {clip_name} already exists, skipping")
                    continue

                print(f"\n{'─'*60}")
                print(f"  Processing hook #{i}/{len(hooks)}  {icons}  score={hook['score']}")
                print(f"  {hook['timestamp']} → +{args.hook_clip_length}s")
                print(f'  "{hook["hook_preview"]}"')
                print(f"{'─'*60}")

                try:
                    ok = process_hook_segment(
                        source_video   = video_path,
                        hook           = hook,
                        clip_length    = args.hook_clip_length,
                        seg_dir        = seg_dir,
                        clip_path      = clip_path,
                        all_words      = all_words,
                        model_name     = args.whisper_model,
                        words_per_line = args.words_per_line,
                        subtitle_delay = args.subtitle_delay,
                        font           = resolved_font,
                        no_vertical    = args.no_vertical,
                        no_burn_subs   = args.no_burn_subs,
                        allowed_modes  = allowed_modes,
                    )
                    if ok:
                        print(f"\n✅  Saved → {clip_name}")
                except Exception as e:
                    print(f"\n⚠️  Hook #{i} failed: {e}")
                finally:
                    # Clean up this segment's working files immediately
                    if seg_dir.exists():
                        _shutil.rmtree(seg_dir, ignore_errors=True)

            print(f"\n🎉  {len(hooks)} hook clip(s) saved to: {clips_dir}")

    else:
        # ── NORMAL MODE: full video pipeline ──

        # Step 2: Reframe to vertical
        face_info = None
        if not args.no_vertical:
            working_video, face_info = reframe_to_vertical(video_path, output_dir, allowed_modes=allowed_modes)
            if face_info:
                _fps_used = face_info.get("fps", 25)
                for s in face_info.get("scenes", []):
                    s["start_sec"] = s["start"] / _fps_used
                    s["end_sec"]   = s["end"]   / _fps_used
        else:
            working_video = video_path
            print("\n\u23e9  Skipping vertical reframe (--no-vertical)")

        # Step 3 & 4: Transcribe + burn subs
        scenes_for_subs = face_info.get("scenes") if face_info else None
        clip_words = None
        if not args.no_transcribe:
            srt_path, clip_words = transcribe_video(working_video, args.whisper_model, output_dir,
                                        args.words_per_line, args.subtitle_delay)
            if not args.no_burn_subs:
                final_video = burn_subtitles(working_video, srt_path, output_dir,
                                             font=resolved_font, scenes=scenes_for_subs)
            else:
                final_video = working_video
                print("\n\u23e9  Skipping subtitle burning (--no-burn-subs)")
        else:
            final_video = working_video
            print("\n\u23e9  Skipping transcription (--no-transcribe)")

        # Step 5: Cut into uniform clips — named after each clip's own transcript
        # when available (that filename becomes the TikTok title on upload)
        cut_into_clips(final_video, args.clip_length, clips_dir, all_words=clip_words,
                       use_llm_titles=not args.no_llm_titles)

    # ── Cleanup: remove working files, keep only clips ──
    print(f"\n🧹  Cleaning up working files...")
    _shutil.rmtree(output_dir, ignore_errors=True)
    print(f"\n✅  All done! Your clips are in: {clips_dir}")


if __name__ == "__main__":
    main()
