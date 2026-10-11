"""Transcription stage of the video processor."""

import json
import math
import wave
from pathlib import Path
from .media import _extract_audio, _get_audio_duration, _run_ffmpeg


CHUNK_SEC   = 15 * 60   # 15 min of audio per chunk — keeps peak memory bounded regardless


OVERLAP_SEC = 8         # extra audio fed to whisper on each side of a chunk boundary so it


def _read_pcm16_mono(path: Path):
    """Load the ffmpeg-generated 16 kHz PCM chunk as a float32 waveform."""
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError(f"Unexpected audio format in {path}")
        samples = audio.readframes(audio.getnframes())
    return np.frombuffer(samples, dtype="<i2").astype(np.float32) / 32768.0


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
                _read_pcm16_mono(chunk_path),
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


def transcribe_audio_only(video_path: Path, model_name: str, output_dir: Path) -> list:
    """
    Transcribe the full video audio (chunked) and return the raw per-word list.
    Does not write an SRT; uniform clips and hook scoring use these words.
    Saves a run-local .words.json so stages in the same run can share it.
    """
    words_json_path = output_dir / (video_path.stem + ".words.json")
    if words_json_path.exists():
        print(f"\n⏩  Transcript already exists → {words_json_path.name}")
        with open(words_json_path, encoding="utf-8") as f:
            return json.load(f)["words"]

    print(f"\n🏙️  Transcribing audio ({model_name} model) …")
    print("    (audio-only pass — no video processing yet)")

    audio_path = _extract_audio(video_path, output_dir)

    all_words, language, language_prob = _transcribe_words_chunked(audio_path, model_name, output_dir)

    print(f"    Language: {language} ({(language_prob or 0.0):.0%})")
    print(f"    Got {len(all_words)} words")

    with open(words_json_path, "w", encoding="utf-8") as f:
        json.dump({"words": all_words, "words_per_chunk": 5, "delay": 0.0}, f)
    print(f"✅  Transcript saved → {words_json_path.name}")
    return all_words


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


