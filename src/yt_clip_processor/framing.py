"""Framing for vertical video. """

from pathlib import Path
from .faces import analyse_faces
from .media import _get_video_codec, _run_ffmpeg
from .rendering import _reframe_center_crop, _render_with_tracking, render_split_screen
from .scenes import _smooth_crop_path


def reframe_to_vertical(video_path: Path, output_dir: Path, allowed_modes: set = None,
                        speech_words: list = None):
    """
    Smart reframe to 9:16 vertical.
    Returns (vertical_path, face_info). face_info is None if already cached.
    - 2 faces consistently present -> split-screen mode (top/bottom halves)
    - 1 face -> single face tracking mode
    - screen capture with lower corner camera -> content and camera panes
    - sustained 0 faces -> enlarged centered wide view
    """
    vertical_path = output_dir / (video_path.stem + "_vertical.mp4")

    if vertical_path.exists():
        print(f"\u23e9  Vertical video already exists \u279c {vertical_path.name}")
        return vertical_path, None  # face_info not available for cached output

    print(f"\n\U0001f4f1  Reframing to 9:16...")

    try:
        import cv2
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

    if abs(src_w / src_h - 9 / 16) <= 0.01:
        print("    ⏩  Source is already 9:16 — using it without face analysis or a second encode")
        return working_path, None

    sample_every = max(1, int(fps * 1.0))
    print(f"    Source: {src_w}x{src_h} | Sampling every {sample_every} frames")
    _modes_for_log = allowed_modes if allowed_modes else {'single', 'dual', 'reaction'}
    print(f"    Scene types searched: {', '.join(sorted(_modes_for_log))}")

    # ── Analyse faces ──
    face_info = analyse_faces(working_path, sample_every=sample_every,
                              allowed_modes=allowed_modes, speech_words=speech_words)

    has_dual     = any(s["mode"] == "dual"     for s in face_info.get("scenes", []))
    has_reaction = any(s["mode"] == "reaction" for s in face_info.get("scenes", []))
    has_screen   = any(s["mode"] == "screen"   for s in face_info.get("scenes", []))
    has_wide     = any(s["mode"] == "wide"     for s in face_info.get("scenes", []))

    if has_dual or has_reaction or has_screen or has_wide:
        # Scene-aware render switches between split-screen, reaction, face tracking, and wide shots.
        kinds = " + ".join(k for k, v in (("dual", has_dual), ("reaction", has_reaction),
                                         ("screen", has_screen), ("wide", has_wide)) if v)
        print(f"    \U0001f465  {kinds.capitalize()} scene(s) detected \u2014 scene-aware render...")
        success = render_split_screen(
            working_path, vertical_path,
            face_info["face_data"],
            fps, src_w, src_h, sample_every,
            scenes=face_info["scenes"],
            panels=face_info.get("panels"),
            active_speakers=face_info.get("active_speakers"),
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

    all_crop_x = _smooth_crop_path(keyframes, total, default_x)
    print(f"    Rendering face-tracked video (this takes a while)...")
    success = _render_with_tracking(working_path, vertical_path, all_crop_x, crop_w, fps, face_data=face_info.get('face_data'))

    if not success:
        print("    \u26a0\ufe0f  Render failed, falling back to center crop")
        return _reframe_center_crop(video_path, output_dir), face_info

    print(f"\u2705  Face-tracked vertical video \u279c {vertical_path.name}")
    return vertical_path, face_info
