"""Scene decisions and full-frame fallback for debate footage."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.faces import _classify_keyframe_mode
from yt_clip_processor.rendering import _fit_full_frame
from yt_clip_processor.scenes import _smooth_mode_sequence


class SceneModeTests(unittest.TestCase):
    def test_zero_faces_become_a_wide_shot_after_two_samples(self):
        modes = {
            0: _classify_keyframe_mode({0: (50, 50, 20, 20)}, 100, 100),
            1: _classify_keyframe_mode({}, 100, 100),
            2: _classify_keyframe_mode({}, 100, 100),
            3: _classify_keyframe_mode({}, 100, 100),
            4: _classify_keyframe_mode({0: (50, 50, 20, 20)}, 100, 100),
            5: _classify_keyframe_mode({0: (50, 50, 20, 20)}, 100, 100),
        }
        result = _smooth_mode_sequence(modes, {"single": 2, "wide": 2})
        self.assertEqual(result[1], "wide")
        self.assertEqual(result[2], "wide")
        self.assertEqual(result[4], "single")
        self.assertEqual(result[5], "single")

    def test_wide_shot_preserves_both_sides_of_landscape_frame(self):
        import numpy as np

        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        frame[:, :20] = (255, 0, 0)
        frame[:, -20:] = (0, 0, 255)
        fitted = _fit_full_frame(frame, 72, 128)
        self.assertEqual(fitted.shape, (128, 72, 3))
        self.assertTrue((fitted[64, 2] == (255, 0, 0)).all())
        self.assertTrue((fitted[64, -3] == (0, 0, 255)).all())


if __name__ == "__main__":
    unittest.main()
