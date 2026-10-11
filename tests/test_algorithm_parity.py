"""Check that extracted algorithms still match the untouched prototype."""

import importlib.util
import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from yt_clip_processor.scenes import _build_smooth_positions, _smooth_crop_path

spec = importlib.util.spec_from_file_location(
    "reference_prototype", root / "prototype" / "yt_clip_processor_prototype.py"
)
prototype = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prototype)


class AlgorithmParityTests(unittest.TestCase):
    def test_crop_interpolation_matches_prototype(self):
        keyframes = {0: 10, 25: 30, 50: None, 75: 40}
        self.assertEqual(
            _smooth_crop_path(keyframes, 100, 20),
            prototype._smooth_crop_path(keyframes, 100, 25, 20),
        )

    def test_face_path_interpolates_across_one_second_gap(self):
        faces = {
            0: {0: (0, 20, 10, 10)},
            25: {0: (100, 20, 10, 10)},
        }
        positions = _build_smooth_positions(
            faces, face_id=0, axis="x", default=0,
            sample_every=25, fps=25,
        )
        self.assertTrue(40 <= positions[12] <= 60)


if __name__ == "__main__":
    unittest.main()
