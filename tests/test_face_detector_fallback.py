"""Regression for podium faces missed by the short-range MediaPipe model."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor import faces


class DetectorFallbackTests(unittest.TestCase):
    def test_full_range_recovers_speaker_but_ignores_tiny_distant_face(self):
        short = Mock()
        full = Mock()
        with (
            patch.object(faces, "_create_mediapipe_face_detector", side_effect=[short, full]) as create,
            patch.object(faces, "_detect_faces_mediapipe", side_effect=[
                [], [(600, 220, 95, 95)],
                [], [(500, 300, 40, 40)],
                [], [(960, 190, 85, 85)],
            ]),
        ):
            detector = faces._FaceDetectorCascade()
            self.assertEqual(detector.detect(object(), 1000, 1280, 720), [(600, 220, 95, 95)])
            self.assertEqual(detector.detect(object(), 2000, 1280, 720), [])
            self.assertEqual(detector.detect(object(), 3000, 1280, 720), [])
            detector.close()
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[1].kwargs, {"full_range": True})
        short.close.assert_called_once()
        full.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
