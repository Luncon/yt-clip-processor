"""Subtitle timestamp behavior at rounding boundaries."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.subtitles import _write_karaoke_ass


class SubtitleTests(unittest.TestCase):
    def test_ass_timestamp_rounding_carries_into_next_second(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            words = root / "words.json"
            output = root / "subs.ass"
            words.write_text(json.dumps({
                "words": [{"word": "Hello", "start": 0.995, "end": 1.2}],
                "words_per_chunk": 1,
                "delay": 0,
            }))
            _write_karaoke_ass(words, output)
            dialogue = next(line for line in output.read_text().splitlines() if line.startswith("Dialogue:"))
            self.assertIn(",0:00:01.00,", dialogue)

    def test_screen_layout_subtitles_use_space_above_camera_pane(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            words = root / "words.json"
            output = root / "subs.ass"
            words.write_text(json.dumps({
                "words": [{"word": "Hello", "start": 1.0, "end": 1.4}],
                "words_per_chunk": 1,
                "delay": 0,
            }))
            _write_karaoke_ass(words, output, scenes=[
                {"start_sec": 0, "end_sec": 2, "mode": "screen"}])
            content = output.read_text()
            self.assertIn("Style: Screen", content)
            dialogue = next(line for line in content.splitlines() if line.startswith("Dialogue:"))
            self.assertIn(",Screen,", dialogue)


if __name__ == "__main__":
    unittest.main()
