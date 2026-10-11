"""Visual layout decisions for news panels and screen captures."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.layout import (detect_panel_dividers, infer_active_speakers,
                                      is_camera_cut, mouth_motion)
from yt_clip_processor.rendering import (_dual_scene_box, _fit_panel,
                                         _next_split_ratio, _screen_boxes)
from yt_clip_processor import faces as face_module
from yt_clip_processor.faces import _classify_keyframe_mode
from yt_clip_processor.scenes import _build_scenes, _smooth_mode_sequence


class LayoutAnalysisTests(unittest.TestCase):
    def test_straight_news_panel_divider_is_detected(self):
        import numpy as np

        frame = np.full((180, 320, 3), 30, dtype=np.uint8)
        frame[:, 160:] = 210
        self.assertAlmostEqual(detect_panel_dividers(frame)["x"], 160, delta=2)
        stacked = np.full((180, 320, 3), 30, dtype=np.uint8)
        stacked[90:] = 210
        self.assertAlmostEqual(detect_panel_dividers(stacked)["y"], 90, delta=2)

    def test_small_face_edges_do_not_count_as_panel(self):
        import numpy as np

        frame = np.full((180, 320, 3), 50, dtype=np.uint8)
        frame[70:110, 145:175] = 210
        self.assertIsNone(detect_panel_dividers(frame)["x"])

    def test_camera_cut_splits_scene_even_when_mode_is_unchanged(self):
        import numpy as np

        before = np.zeros((90, 160, 3), dtype=np.uint8)
        after = np.full_like(before, 255)
        self.assertTrue(is_camera_cut(before, after))
        self.assertFalse(is_camera_cut(before, before.copy()))
        self.assertEqual(_build_scenes({0: "dual", 25: "dual", 50: "dual"}, 75, cuts={25}), [
            {"start": 0, "end": 25, "mode": "dual"},
            {"start": 25, "end": 75, "mode": "dual"},
        ])

    def test_confirmed_screen_layout_starts_at_first_screen_sample(self):
        raw = {0: "screen", 25: "screen", 50: "reaction", 75: "screen",
               100: "screen", 125: "screen", 150: "screen"}
        smoothed = _smooth_mode_sequence(raw, {"screen": 6, "reaction": 6})
        self.assertEqual(smoothed[0], "screen")
        self.assertEqual(smoothed[50], "screen")
        cut_modes = {0: "screen", 25: "screen", 50: "screen", 75: "dual"}
        after_cut = _smooth_mode_sequence(cut_modes, {"screen": 3, "dual": 3},
                                          cuts={75})
        self.assertEqual(after_cut[0], "screen")
        self.assertEqual(after_cut[75], "single")

    def test_corner_camera_over_screen_is_not_two_person_interview(self):
        faces = {0: (130, 90, 60, 72), 1: (265, 145, 36, 30)}
        self.assertEqual(_classify_keyframe_mode(
            faces, 320, 180, panel={"x": 230, "y": None}), "screen")
        self.assertEqual(_classify_keyframe_mode(
            faces, 320, 180, panel={"x": None, "y": None}), "dual")
        self.assertEqual(_classify_keyframe_mode(
            {0: (265, 145, 36, 30)}, 320, 180), "screen")

    def test_dual_crop_uses_own_panel_and_covers_later_profile(self):
        samples = [(110, 80, 35, 45), (135, 82, 42, 46)]
        box = _dual_scene_box(samples, 320, 180, (0, 160))
        self.assertLessEqual(box[2], 160)
        self.assertLessEqual(135 + 42 / 2, box[2])
        crossing = _dual_scene_box([(155, 82, 42, 46)], 320, 180, (0, 160))
        self.assertGreater(crossing[2], 160)
        top = _dual_scene_box([(150, 45, 40, 30)], 320, 180,
                              y_bounds=(0, 90))
        self.assertLessEqual(top[3], 90)

    def test_screen_layout_keeps_content_and_corner_camera(self):
        content, camera = _screen_boxes((265, 145, 36, 30), 320, 180, 230)
        self.assertEqual(content, (0, 0, 230, 180))
        self.assertLessEqual(camera[0], 247)
        self.assertGreaterEqual(camera[2], 283)
        _, bounded_camera = _screen_boxes((265, 145, 36, 30), 320, 180,
                                          230, camera_x=190, camera_y=105)
        self.assertEqual(bounded_camera, (190, 105, 320, 180))
        import numpy as np
        frame = np.full((180, 230, 3), 100, dtype=np.uint8)
        frame[:, 0] = 255
        fitted = _fit_panel(frame, 720, 896)
        self.assertEqual(fitted.shape, (896, 720, 3))
        self.assertTrue(np.any(fitted[:, 0, :] == 255))

    def test_speaker_focus_requires_speech_and_repeated_clear_motion(self):
        scores = {0: {0: 8, 1: 1}, 25: {0: 9, 1: 2},
                  50: {0: 2, 1: 10}, 75: {0: 1, 1: 11},
                  100: {0: 5, 1: 5}}
        words = [{"start": second, "end": second + 0.4}
                 for second in range(5)]
        focused = infer_active_speakers(scores, words, fps=25)
        self.assertIsNone(focused[0])
        self.assertEqual(focused[25], 0)
        self.assertEqual(focused[75], 1)
        self.assertIsNone(focused[100])
        self.assertTrue(all(value is None for value in
                            infer_active_speakers(scores, [], fps=25).values()))
        self.assertEqual(_next_split_ratio(0.5, None), 0.5)
        self.assertAlmostEqual(_next_split_ratio(0.5, 0), 0.51)
        self.assertAlmostEqual(_next_split_ratio(0.55, None), 0.54)

    def test_mouth_change_has_more_motion_than_static_face(self):
        import numpy as np

        previous = np.zeros((180, 320), dtype=np.uint8)
        current = previous.copy()
        current[89:98, 155:165] = 200
        moving = mouth_motion(previous, current, (160, 80, 50, 60), 320, 180)
        self.assertGreater(moving, 5)
        self.assertEqual(mouth_motion(previous, previous, (160, 80, 50, 60), 320, 180), 0)

    def test_corner_detection_adds_small_webcam_when_main_face_was_found(self):
        import numpy as np

        frame = np.zeros((180, 320, 3), dtype=np.uint8)
        with (patch.object(face_module, "_create_mediapipe_face_detector", return_value=object()),
              patch.object(face_module, "_detect_faces_mediapipe",
                           side_effect=[[(100, 90, 50, 65)], [(70, 45, 30, 28)]])):
            cascade = face_module._FaceDetectorCascade()
            result = cascade.detect(frame, 1000, 320, 180,
                                    panel={"x": 230, "y": None})
        self.assertIn((100, 90, 50, 65), result)
        self.assertIn((round(320 * 0.52) + 70, round(180 * 0.50) + 45, 30, 28), result)


if __name__ == "__main__":
    unittest.main()
