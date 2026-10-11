"""Render vertical video using tracked and scene-specific crops."""

import subprocess
from bisect import bisect_left
from pathlib import Path
from .faces import _is_reaction_face
from .media import _run_ffmpeg
from .scenes import _build_smooth_positions


def _render_with_tracking(
    video_path: Path,
    out_path: Path,
    crop_x_list: list,
    crop_w: int,
    fps: float,
    face_data: dict = None,   # keyframe→face dict from analyse_faces(), used to gate letterbox
) -> bool:
    """Crop decoded frames in OpenCV and pipe them to ffmpeg for encoding."""
    try:
        import cv2
        import numpy as np

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
            "-map", "1:a?",
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
        def _face_present_at(fidx: int) -> bool:
            """Return True if a face was detected at or near this frame index."""
            if not _fd_keys:
                return False
            position = bisect_left(_fd_keys, fidx)
            nearby = _fd_keys[max(0, position - 1):position + 1]
            nearest = min(nearby, key=lambda k: abs(k - fidx))
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
                scale     = min(1080 / src_w_frame, 1920 / src_h_frame)
                scaled_w  = min(1080, int(src_w_frame * scale))
                scaled_h  = min(1920, int(src_h_frame * scale))
                pad_left  = (1080 - scaled_w) // 2
                pad_top   = (1920 - scaled_h) // 2
                scaled    = cv2.resize(frame, (scaled_w, scaled_h), interpolation=cv2.INTER_LINEAR)
                resized   = np.zeros((1920, 1080, 3), dtype=np.uint8)
                resized[pad_top : pad_top + scaled_h, pad_left : pad_left + scaled_w] = scaled
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


def _reframe_center_crop(video_path: Path, output_dir: Path) -> Path:
    """Fallback: plain center crop to 9:16 via ffmpeg."""
    vertical_path = output_dir / (video_path.stem + "_vertical.mp4")
    if vertical_path.exists():
        return vertical_path
    print(f"\n\U0001f4f1  Center-cropping to 9:16 (1080x1920)...")
    vf  = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
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


def _fit_full_frame(frame, out_w: int, out_h: int):
    """Fit a complete source frame on a vertical canvas without cropping it."""
    import cv2
    import numpy as np

    src_h, src_w = frame.shape[:2]
    scale = min(out_w / src_w, out_h / src_h)
    width = max(1, min(out_w, round(src_w * scale)))
    height = max(1, min(out_h, round(src_h * scale)))
    resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    x = (out_w - width) // 2
    y = (out_h - height) // 2
    canvas[y:y + height, x:x + width] = resized
    return canvas


def render_split_screen(
    video_path: Path,
    out_path: Path,
    face_data: dict,
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
    - Wide scenes:     fit the complete source frame when faces are absent
    Faces are identified by X position (left=0, right=1) so they never swap.
    `scenes` must be the smoothed scene list from analyse_faces() — if omitted,
    falls back to raw face_data (legacy behaviour, prone to jump-cut flicker,
    and without src_w/src_h it can't distinguish reaction from single).
    """
    import cv2
    import numpy as np

    OUT_W, OUT_H = 720, 1280
    HALF_H       = OUT_H // 2

    # Build per-keyframe mode lookup from the SMOOTHED scenes list.
    # This is critical — using raw face_data here bypasses all the hysteresis
    # work done in _smooth_mode_sequence and causes jump-cut false positives.
    if scenes:
        scene_mode_per_frame = {}
        for kf in sorted(face_data.keys()):
            mode = 'single'
            for s in scenes:
                if s['start'] <= kf < s['end']:
                    mode = s['mode']
                    break
            scene_mode_per_frame[kf] = mode
    else:
        # Fallback: derive from raw face_data (legacy)
        scene_mode_per_frame = _build_scene_mode_lookup(face_data, src_w, src_h)

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
            'x': _build_smooth_positions(face_data, fid, 'x', src_w // 2, sample_every, boundaries, fps=fps),
            'y': _build_smooth_positions(face_data, fid, 'y', src_h // 2, sample_every, boundaries, fps=fps),
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
        "-map", "0:v", "-map", "1:a?",
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

        elif mode == 'wide':
            canvas = _fit_full_frame(frame, OUT_W, OUT_H)

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

def _build_scene_mode_lookup(face_data: dict, src_w: int = None, src_h: int = None) -> dict:
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
        elif not faces:
            modes[k] = 'wide'
        elif len(faces) == 1 and src_w and src_h and _is_reaction_face(faces[0], src_w, src_h):
            modes[k] = 'reaction'
        else:
            modes[k] = 'single'
    return modes
