"""Scene segmentation and camera path smoothing."""

from bisect import bisect_right

def _smooth_crop_path(keyframes: dict, total_frames: int, default_x: int) -> list:
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
        position = bisect_right(sorted_keys, i)
        before = sorted_keys[position - 1] if position else None
        after = sorted_keys[position] if position < len(sorted_keys) else None
        if before is not None and after is not None:
            k1, k2 = before, after
            t = (i - k1) / (k2 - k1)
            x = int(raw[k1] + t * (raw[k2] - raw[k1]))
        elif before is not None:
            x = raw[before]
        elif after is not None:
            x = raw[after]
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
            if raw == 'wide':
                # An empty shot needs the full source frame from its first
                # sample. Confirm a consecutive run before backdating it so
                # an isolated missed face does not flash the wide layout.
                first = idx - threshold + 1
                if first >= 0 and all(mode == 'wide' for mode in raw_seq[first:idx + 1]):
                    cur_mode = raw
                    for earlier in keys[first:idx]:
                        result[earlier] = raw
            else:
                window = threshold + TOLERANCE
                recent = raw_seq[max(0, idx - window + 1): idx + 1]
                if recent.count(raw) >= threshold:
                    if cur_mode == 'wide':
                        first = idx
                        while first > 0 and raw_seq[first - 1] == raw:
                            first -= 1
                        for earlier in keys[first:idx]:
                            result[earlier] = raw
                    cur_mode = raw
        result[k] = cur_mode

    return result


def _build_scenes(smoothed_modes: dict, total_frames: int) -> list:
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


def _build_smooth_positions(face_data: dict, face_id: int, axis: str,
                             default: int, sample_every: int,
                             scene_boundaries: list = None, fps: float = 25.0) -> list:
    """
    Build a smooth per-frame position array for one face on one axis.
    Smoothing is applied within scenes only — never across scene boundaries.
    This prevents the camera from slowly panning into position after a cut.
    """
    try:
        import numpy as np
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
    multi_face_keys = sorted(multi_face)
    boundaries = sorted(scene_boundaries or [])
    result      = []

    # Find max gap between detections — if gap is short, interpolate smoothly.
    # If gap is long (>2s worth of frames), hold last position instead of
    # interpolating across it (which causes slow pans through empty space).
    max_gap_frames = max(1, int(2.0 * fps))

    for i in range(total):
        position = bisect_right(sorted_keys, i)
        before = sorted_keys[position - 1] if position else None
        after = sorted_keys[position] if position < len(sorted_keys) else None
        if before is not None and after is not None:
            k1, k2 = before, after
            gap = k2 - k1

            # Clean cut across scene boundary — snap, don't pan
            if boundaries:
                crossed = bisect_right(boundaries, k1) < bisect_right(boundaries, i)
                if crossed:
                    result.append(raw.get(after, default))
                    continue

            has_multi_face = bisect_right(multi_face_keys, k1) < bisect_right(multi_face_keys, k2)
            if gap > max_gap_frames or has_multi_face:
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
        elif before is not None:
            result.append(raw[before])
        elif after is not None:
            result.append(raw[after])
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

