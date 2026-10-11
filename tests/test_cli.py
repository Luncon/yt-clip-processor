"""CLI contract tests that do not require video dependencies."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.cli import parse_args


class CliValidationTests(unittest.TestCase):
    def assert_invalid(self, arguments):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(arguments)

    def test_rejects_non_positive_lengths_and_words(self):
        for option in ("--clip-length", "--hook-clip-length", "--words-per-line"):
            with self.subTest(option=option):
                self.assert_invalid(["https://youtu.be/dQw4w9WgXcQ", option, "0"])

    def test_rejects_hooks_without_transcription(self):
        self.assert_invalid(["https://youtu.be/dQw4w9WgXcQ", "--hooks", "2", "--no-transcribe"])

    def test_accepts_local_copy_path(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.touch()
            args = parse_args([str(source), "--no-transcribe", "--no-vertical"])
            self.assertTrue(args.no_transcribe)
            self.assertTrue(args.no_vertical)

    def test_rejects_unknown_source_and_trim_range(self):
        self.assert_invalid(["missing-video.mp4"])
        self.assert_invalid(["https://example.com/video"])
        self.assert_invalid(["https://youtu.be/dQw4w9WgXcQ", "--start", "20", "--end", "10"])
        self.assert_invalid(["https://youtu.be/dQw4w9WgXcQ", "--start", "nan"])

    def test_accepts_youtube_url(self):
        args = parse_args(["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
        self.assertEqual(args.hooks, 0)


if __name__ == "__main__":
    unittest.main()
