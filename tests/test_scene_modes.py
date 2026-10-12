"""Scene decisions and portrait layout for landscape footage."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.faces import _classify_keyframe_mode
from yt_clip_processor.rendering import _dual_crop_box, _fit_centered_wide
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

    def test_dual_crop_keeps_a_profile_crossing_the_source_midpoint(self):
        import numpy as np

        frame = np.zeros((108, 192, 3), dtype=np.uint8)
        frame[30:75, 80:103] = (0, 255, 0)  # left speaker's profile
        box = _dual_crop_box((90, 52, 23, 45), 192, 108)
        x1, y1, x2, y2 = box
        crop = frame[y1:y2, x1:x2]

        self.assertGreater(x2, 96)
        self.assertEqual(np.count_nonzero(crop[:, :, 1]), 45 * 23)
        self.assertLess(x2 - x1, 192)  # still focused on one speaker

        right_box = _dual_crop_box((102, 52, 23, 45), 192, 108)
        self.assertLess(right_box[0], 96)
        self.assertEqual(np.count_nonzero(
            frame[right_box[1]:right_box[3], right_box[0]:right_box[2], 1]
        ), 45 * 23)

    def test_wide_shot_enlarges_center_without_filling_entire_canvas(self):
        import numpy as np

        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        frame[:, :20] = (255, 0, 0)
        frame[:, -20:] = (0, 0, 255)
        frame[:, 65:95] = (0, 255, 0)
        fitted = _fit_centered_wide(frame, 72, 128)
        self.assertEqual(fitted.shape, (128, 72, 3))
        self.assertTrue((fitted[64, 36] == (0, 255, 0)).all())
        self.assertTrue((fitted[64, 2] == (0, 0, 0)).all())
        self.assertTrue((fitted[64, -3] == (0, 0, 0)).all())
        occupied_rows = np.flatnonzero(np.any(fitted != 0, axis=(1, 2)))
        self.assertGreaterEqual(len(occupied_rows), 83)  # at least 65% of 128
        self.assertLess(len(occupied_rows), 128)


if __name__ == "__main__":
    unittest.main()
