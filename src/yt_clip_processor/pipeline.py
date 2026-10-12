"""Orchestrate video processing while owning only run-specific files."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from .framing import reframe_to_vertical
from .hooks import _print_hook_summary, _words_in_range, find_hook_clips
from .media import _get_duration, _run_ffmpeg, trim_video
from .semantic import semantic_scores
from .sources import download_video
from .subtitles import _resolve_font, burn_subtitles
from .titles import generate_clip_title
from .transcription import _write_srt_from_words, transcribe_audio_only


def process_hook_segment(
    source_video:  Path,
    hook:          dict,
    seg_dir:       Path,
    clip_path:     Path,
    all_words:     list,
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
    seg_words = [
        {"word": w["word"],
         "start": round(w["start"] - start_sec, 3),
         "end": round(w["end"] - start_sec, 3)}
        for w in all_words
        if w["start"] >= start_sec - 0.1 and w["end"] <= end_sec + 0.5
    ]

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
        working, face_info = reframe_to_vertical(
            raw_seg, seg_dir, allowed_modes=allowed_modes, speech_words=seg_words)
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
    shutil.move(str(final_seg), str(clip_path))
    return True


def cut_into_clips(video_path: Path, clip_length: int, clips_dir: Path,
                   all_words: list = None, use_llm_titles: bool = True,
                   subtitle_work_dir: Path = None, words_per_line: int = 5,
                   subtitle_delay: float = 0.0, font: str = "Arial",
                   scenes: list = None):
    """
    Split the video into clips of `clip_length` seconds each, burning subtitles
    during the final encode when a subtitle work directory is supplied.
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

    start_times = [word["start"] for word in all_words] if all_words else None
    completed = 0
    for i in range(num_clips):
        start = i * clip_length
        end   = min(start + clip_length, duration)

        clip_words = _words_in_range(all_words, start, end, start_times) if all_words else []
        if clip_words:
            clip_text  = " ".join(w["word"] for w in clip_words)
            title      = generate_clip_title(clip_text, use_llm=use_llm_titles)
            clip_path  = clips_dir / f"{i+1:02d}_{title}.mp4"
        else:
            clip_path  = clips_dir / f"clip_{i+1:03d}.mp4"

        if clip_path.exists():
            print(f"    ⏩  {clip_path.name} already exists, skipping")
            completed += 1
            continue

        if subtitle_work_dir is not None and clip_words:
            srt_stub = subtitle_work_dir / f"clip_{i+1:03d}.srt"
            words_json = srt_stub.with_suffix(".words.json")
            relative_words = [
                {"word": word["word"],
                 "start": max(0.0, word["start"] - start),
                 "end": min(end - start, word["end"] - start)}
                for word in clip_words
            ]
            words_json.write_text(json.dumps({
                "words": relative_words,
                "words_per_chunk": words_per_line,
                "delay": subtitle_delay,
            }), encoding="utf-8")
            clip_scenes = [
                {"start_sec": max(0.0, scene["start_sec"] - start),
                 "end_sec": min(end - start, scene["end_sec"] - start),
                 "mode": scene["mode"]}
                for scene in (scenes or [])
                if scene["start_sec"] < end and scene["end_sec"] > start
            ]
            try:
                burn_subtitles(
                    video_path, srt_stub, subtitle_work_dir,
                    font=font, scenes=clip_scenes, output_path=clip_path,
                    start=start, duration=end - start,
                )
            finally:
                words_json.unlink(missing_ok=True)
        else:
            cmd = [
                "ffmpeg", "-y", "-ss", str(start), "-i", str(video_path),
                "-t", str(end - start),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "192k",
                str(clip_path),
            ]
            _run_ffmpeg(cmd, quiet=True)
        completed += 1
        print(f"    ✅  {clip_path.name}  ({start}s – {min(start+clip_length, duration):.0f}s)")

    print(f"\n🎉  Done! {completed} clips saved to: {clips_dir}")
    return completed


def _run_hooks(args, video_path, work_dir, clips_dir, allowed_modes, font):
    words = transcribe_audio_only(video_path, args.whisper_model, work_dir)
    hooks = find_hook_clips(
        words,
        n_hooks=args.hooks,
        clip_length=args.hook_clip_length,
        min_score=args.min_auto_score,
        semantic_scorer=(semantic_scores if os.environ.get("GROQ_API_KEY")
                         and not args.no_semantic_rank else None),
    )
    _print_hook_summary(hooks)
    manifest = {
        "source": args.source_decision or {"url": args.url, "reason": "explicit input"},
        "requested_clips": args.hooks,
        "minimum_score": args.min_auto_score,
        "clips": [],
    }
    if not hooks:
        (clips_dir / "selection.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("No clips passed the automatic quality threshold.")
        return 0

    completed = 0
    for index, hook in enumerate(hooks, 1):
        decision = {key: value for key, value in hook.items() if key != "clip_text"}
        title = generate_clip_title(
            hook.get("clip_text") or hook.get("hook_preview", ""),
            use_llm=not args.no_llm_titles,
        )
        clip_path = clips_dir / f"{index:02d}_{title}.mp4"
        segment_dir = work_dir / f"segment_{index:02d}"
        try:
            process_hook_segment(
                source_video=video_path,
                hook=hook,
                seg_dir=segment_dir,
                clip_path=clip_path,
                all_words=words,
                words_per_line=args.words_per_line,
                subtitle_delay=args.subtitle_delay,
                font=font,
                no_vertical=args.no_vertical,
                no_burn_subs=args.no_burn_subs,
                allowed_modes=allowed_modes,
            )
            completed += 1
            decision["file"] = clip_path.name
            decision["status"] = "rendered"
            print(f"Saved {clip_path}")
        except Exception as exc:
            decision["status"] = "failed"
            decision["error"] = str(exc)
            print(f"Hook {index} failed: {exc}")
        finally:
            manifest["clips"].append(decision)
            shutil.rmtree(segment_dir, ignore_errors=True)
    (clips_dir / "selection.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not completed:
        raise RuntimeError("All selected hooks failed to render")
    return completed


def _run_uniform(args, video_path, work_dir, clips_dir, allowed_modes, font):
    words = None
    if not args.no_transcribe:
        words = transcribe_audio_only(video_path, args.whisper_model, work_dir)

    face_info = None
    working_video = video_path
    if not args.no_vertical:
        working_video, face_info = reframe_to_vertical(
            video_path, work_dir, allowed_modes=allowed_modes, speech_words=words
        )
        if face_info:
            fps = face_info.get("fps", 25)
            for scene in face_info.get("scenes", []):
                scene["start_sec"] = scene["start"] / fps
                scene["end_sec"] = scene["end"] / fps

    return cut_into_clips(
        working_video,
        args.clip_length,
        clips_dir,
        all_words=words,
        use_llm_titles=not args.no_llm_titles,
        subtitle_work_dir=work_dir if words and not args.no_burn_subs else None,
        words_per_line=args.words_per_line,
        subtitle_delay=args.subtitle_delay,
        font=font,
        scenes=face_info.get("scenes") if face_info else None,
    )


def run(args):
    """Process one input, leaving completed clips and optional originals behind."""
    base_dir = Path(args.output).resolve()
    work_root = base_dir / ".work"
    work_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="run-", dir=work_root))
    clips_dir = base_dir / "clips" / work_dir.name
    clips_dir.mkdir(parents=True, exist_ok=False)
    allowed_modes = {
        name for name in ("single", "dual", "reaction") if getattr(args, name)
    } or {"single", "dual", "reaction"}

    try:
        font = _resolve_font(args.font)
        local_path = Path(args.url).expanduser()
        if local_path.is_file():
            video_path = local_path
        else:
            video_path = download_video(
                args.url, work_dir, cache_root=base_dir, fresh=args.fresh
            )
            if args.keep_original:
                originals = base_dir / "originals" / work_dir.name
                originals.mkdir(parents=True, exist_ok=True)
                shutil.copy2(video_path, originals / video_path.name)

        if args.start or args.end:
            video_path = trim_video(video_path, work_dir, args.start, args.end)

        if args.hooks:
            count = _run_hooks(args, video_path, work_dir, clips_dir, allowed_modes, font)
        else:
            count = _run_uniform(args, video_path, work_dir, clips_dir, allowed_modes, font)
        print(f"Completed {count} clips in {clips_dir}")
        return clips_dir
    finally:
        shutil.rmtree(work_dir)
