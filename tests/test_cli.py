"""CLI contract tests that do not require video dependencies."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor import cli
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

    def test_auto_clips_and_legacy_alias(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertEqual(parse_args([url, "--auto-clips", "4"]).hooks, 4)
        self.assertEqual(parse_args([url, "--hooks", "3"]).hooks, 3)

    def test_monitor_source_requires_auto_clips_and_no_url(self):
        self.assertTrue(parse_args(["--from-monitor", "--auto-clips", "4"]).from_monitor)
        self.assert_invalid(["--from-monitor"])
        self.assert_invalid(["--from-monitor", "--auto-clips", "4",
                             "https://youtu.be/dQw4w9WgXcQ"])

    def test_monitor_source_resolves_before_processing(self):
        selected = {"url": "https://youtu.be/dQw4w9WgXcQ", "source": "Example",
                    "reason": "rising views"}
        with (patch.object(cli, "choose_monitored_source", return_value=selected),
              patch.object(cli, "check_dependencies"),
              patch.object(cli, "run") as run,
              contextlib.redirect_stdout(io.StringIO())):
            cli.main(["--from-monitor", "--auto-clips", "4"])
        args = run.call_args.args[0]
        self.assertEqual(args.url, selected["url"])
        self.assertEqual(args.source_decision, selected)


if __name__ == "__main__":
    unittest.main()
