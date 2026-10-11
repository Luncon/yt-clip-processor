"""Faces for vertical video. """

from pathlib import Path
from .media import _get_video_codec, _run_ffmpeg
from .scenes import _build_scenes, _smooth_mode_sequence


# The short-range detector can mistake wide-stage scenery for a large face at
# scores just above 0.45. A stricter score preserves both speakers in tested
# debate split shots while keeping those wide shots uncropped.
MEDIAPIPE_FACE_CONFIDENCE = 0.60


MEDIAPIPE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
MEDIAPIPE_FULL_RANGE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_full_range/float16/1/blaze_face_full_range.tflite"
)
# A full-range hit is only a safe substitute for a missing close-range face
# when it is large enough and near the center. Side faces in wide interviews
# should leave the whole two-person frame visible.
MIN_FULL_RANGE_FACE_HEIGHT_RATIO = 0.10
MAX_FULL_RANGE_OFFCENTER_RATIO = 0.35


def _ensure_mediapipe_face_model(full_range: bool = False) -> Path:
    """
    Download the official BlazeFace model once and reuse it on later runs.
    """
    import urllib.request

    model_dir = Path.home() / ".cache" / "yt_clip_processor" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    name = "blaze_face_full_range" if full_range else "blaze_face_short_range"
    model_url = MEDIAPIPE_FULL_RANGE_MODEL_URL if full_range else MEDIAPIPE_MODEL_URL
    model_path = model_dir / f"{name}.tflite"
    if model_path.exists() and model_path.stat().st_size > 100_000:
        return model_path

    print("    📦  Downloading MediaPipe face model (one-time setup)...")
    temp_path = model_path.with_suffix(".download")

    try:
        urllib.request.urlretrieve(model_url, temp_path)
        temp_path.replace(model_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return model_path


def _create_mediapipe_face_detector(full_range: bool = False):
    """
    Create MediaPipe Face Detector in VIDEO mode.

    The rest of the program still receives the original
    (center_x, center_y, width, height) tuple format.
    """
    import mediapipe as mp

    model_path = _ensure_mediapipe_face_model(full_range=full_range)

    options = mp.tasks.vision.FaceDetectorOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        min_detection_confidence=MEDIAPIPE_FACE_CONFIDENCE,
        min_suppression_threshold=0.30,
    )

    return mp.tasks.vision.FaceDetector.create_from_options(options)


class _FaceDetectorCascade:
    """Use the full-range model only when the short-range model misses a face."""

    def __init__(self):
        self.short = _create_mediapipe_face_detector()
        self.full = None
        self.full_unavailable = False

    def detect(self, frame, timestamp_ms: int, src_w: int, src_h: int) -> list:
        detected = _detect_faces_mediapipe(
            self.short, frame, timestamp_ms, src_w, src_h)
        if detected:
            return detected

        if self.full_unavailable:
            return []
        if self.full is None:
            try:
                self.full = _create_mediapipe_face_detector(full_range=True)
            except Exception as exc:
                self.full_unavailable = True
                print(f"    ⚠️  Full-range face model unavailable: {exc}")
                return []

        candidates = _detect_faces_mediapipe(
            self.full, frame, timestamp_ms, src_w, src_h)
        return [
            face for face in candidates
            if face[3] / max(src_h, 1) >= MIN_FULL_RANGE_FACE_HEIGHT_RATIO
            and abs(face[0] - src_w / 2) / max(src_w / 2, 1)
            <= MAX_FULL_RANGE_OFFCENTER_RATIO
        ]

    def close(self):
        self.short.close()
        if self.full is not None:
            self.full.close()


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
        detector = _FaceDetectorCascade()
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
            detected = detector.detect(frame, timestamp_ms, src_w, src_h)

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


def _classify_keyframe_mode(faces: dict, src_w: int, src_h: int,
                            allowed_modes: set = None) -> str:
    """Choose the crop layout for a sampled frame."""
    if allowed_modes is None:
        allowed_modes = {'single', 'dual', 'reaction'}
    if not faces:
        return 'wide'
    if len(faces) == 2 and 'dual' in allowed_modes:
        return 'dual'
    if len(faces) == 1 and 'reaction' in allowed_modes and _is_reaction_face(faces[0], src_w, src_h):
        return 'reaction'
    return 'single'


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

    detector = _FaceDetectorCascade()

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
            detected = detector.detect(frame, timestamp_ms, src_w, src_h)

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

    # Build per-keyframe mode sequence then smooth it. Wide is a safety crop
    # for shots without detectable faces, regardless of requested face modes.
    keyframe_modes = {}
    for fidx in sorted(face_data.keys()):
        keyframe_modes[fidx] = _classify_keyframe_mode(
            face_data[fidx], src_w, src_h, allowed_modes)

    mode_thresholds = {
        'dual':     MIN_DUAL_FRAMES,
        'single':   MIN_SINGLE_FRAMES,
        'reaction': MIN_REACTION_FRAMES,
        'wide':     2,
    }
    smoothed_modes = _smooth_mode_sequence(keyframe_modes, mode_thresholds)

    # Build scene list: [{start_frame, end_frame, mode}]
    scenes = _build_scenes(smoothed_modes, total)

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
