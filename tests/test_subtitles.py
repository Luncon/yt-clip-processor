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


if __name__ == "__main__":
    unittest.main()
