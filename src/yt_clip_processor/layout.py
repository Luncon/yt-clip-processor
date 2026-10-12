"""Conservative visual cues for panel layouts and camera cuts."""


def detect_panel_dividers(frame) -> dict:
    """Find strong straight separators; return source-pixel x/y positions."""
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    small = cv2.resize(frame, (min(width, 480), min(height, 270)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.int16)

    def strongest(diff, span):
        begin, end = round(span * 0.22), round(span * 0.82)
        if end <= begin:
            return None
        continuity = np.mean(diff > 28, axis=0)
        position = begin + int(np.argmax(continuity[begin:end]))
        if continuity[position] < 0.56:
            return None
        return position

    # A chat column can end above a lower-right camera overlay, so inspect
    # the upper portion as well as the complete frame.
    vertical = np.abs(np.diff(gray, axis=1))
    upper = strongest(vertical[:max(1, round(gray.shape[0] * 0.55))], gray.shape[1] - 1)
    full = strongest(vertical, gray.shape[1] - 1)
    x = upper if upper is not None else full
    lower_x = strongest(vertical[round(gray.shape[0] * 0.58):], gray.shape[1] - 1)

    horizontal = np.abs(np.diff(gray, axis=0)).T
    y = strongest(horizontal, gray.shape[0] - 1)
    right_y = strongest(horizontal[round(gray.shape[1] * 0.58):], gray.shape[0] - 1)
    return {
        "x": round((x + 1) * width / gray.shape[1]) if x is not None else None,
        "y": round((y + 1) * height / gray.shape[0]) if y is not None else None,
        "camera_x": round((lower_x + 1) * width / gray.shape[1]) if lower_x is not None else None,
        "camera_y": round((right_y + 1) * height / gray.shape[0]) if right_y is not None else None,
    }


def is_camera_cut(previous, current) -> bool:
    """Detect a large visual change on sampled frames, not ordinary motion."""
    import cv2
    import numpy as np

    size = (96, 54)
    left = cv2.cvtColor(cv2.resize(previous, size), cv2.COLOR_BGR2GRAY)
    right = cv2.cvtColor(cv2.resize(current, size), cv2.COLOR_BGR2GRAY)
    difference = float(np.mean(cv2.absdiff(left, right)))
    if difference < 48:
        return False
    hist_left = cv2.calcHist([left], [0], None, [32], [0, 256])
    hist_right = cv2.calcHist([right], [0], None, [32], [0, 256])
    return cv2.compareHist(hist_left, hist_right, cv2.HISTCMP_CORREL) < 0.80


def mouth_motion(previous_gray, current_gray, face: tuple,
                 src_w: int, src_h: int) -> float:
    """Measure lower-face change after subtracting whole-face movement."""
    import cv2
    import numpy as np

    height, width = current_gray.shape[:2]
    cx, cy, fw, fh = face
    x1 = max(0, round((cx - fw * 0.32) * width / src_w))
    x2 = min(width, round((cx + fw * 0.32) * width / src_w))
    mouth_y1 = max(0, round((cy + fh * 0.16) * height / src_h))
    mouth_y2 = min(height, round((cy + fh * 0.46) * height / src_h))
    upper_y1 = max(0, round((cy - fh * 0.32) * height / src_h))
    upper_y2 = min(height, round((cy - fh * 0.08) * height / src_h))
    if x2 <= x1 or mouth_y2 <= mouth_y1 or upper_y2 <= upper_y1:
        return 0.0
    change = cv2.absdiff(previous_gray, current_gray)
    mouth = float(np.mean(change[mouth_y1:mouth_y2, x1:x2]))
    upper = float(np.mean(change[upper_y1:upper_y2, x1:x2]))
    return max(0.0, mouth - upper * 0.5)


def infer_active_speakers(scores: dict, words: list, fps: float) -> dict:
    """Only choose a panel speaker after two clear speech-aligned samples."""
    if not words:
        return {frame: None for frame in scores}
    spoken_seconds = {second for word in words
                      for second in range(max(0, int(word['start'])),
                                          int(word['end']) + 1)}
    active, pending, count = None, None, 0
    result = {}
    for frame, motions in sorted(scores.items()):
        first, second = motions.get(0, 0), motions.get(1, 0)
        choice = None
        if int(frame / fps) in spoken_seconds and max(first, second) >= 5:
            if first > second * 1.6 and first - second >= 3:
                choice = 0
            elif second > first * 1.6 and second - first >= 3:
                choice = 1
        if choice is None:
            active, pending, count = None, None, 0
        elif choice == pending:
            count += 1
            if count >= 2:
                active = choice
        else:
            pending, count = choice, 1
            active = None
        result[frame] = active
    return result
