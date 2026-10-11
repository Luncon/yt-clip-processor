"""Regressions for clip selection and media processing."""

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor import framing, hooks, pipeline
from yt_clip_processor.cli import parse_args
from yt_clip_processor.rendering import _reframe_center_crop


class HookSelectionTests(unittest.TestCase):
    def test_repeated_topics_are_not_selected_twice(self):
        tokens = "surprising discovery about space travel".split()
        words = [
            {"word": tokens[i % len(tokens)], "start": float(i), "end": i + 0.8}
            for i in range(150)
        ]
        with (
            patch.object(hooks, "_hook_score_chunk", return_value={"score": 80, "signals": {}}),
            patch.object(hooks, "_is_ad_window", return_value=False),
            patch.object(hooks, "_score_clip_body", return_value={"body_score": 60, "body_signals": {}}),
            patch.object(hooks, "_score_standalone_opening", return_value={"score": 60, "reasons": []}),
            patch.object(hooks, "_score_payoff", return_value={"score": 60, "signals": {}}),
            patch.object(hooks, "_score_ending", return_value={"score": 60, "reasons": []}),
        ):
            selected = hooks.find_hook_clips(words, 3, 25)

        self.assertEqual(len(selected), 1)
        self.assertNotIn("token_set", selected[0])

    def test_uniform_transcription_uses_source_audio_before_reframing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            args = parse_args([str(source)])
            vertical = root / "vertical.mp4"
            with (
                patch.object(pipeline, "transcribe_audio_only", return_value=[]) as transcribe,
                patch.object(pipeline, "reframe_to_vertical", return_value=(vertical, None)),
                patch.object(pipeline, "cut_into_clips", return_value=0),
            ):
                pipeline._run_uniform(args, source, root, root / "clips", {"single"}, "Arial")
            transcribe.assert_called_once_with(source, args.whisper_model, root)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
class MediaProcessingTests(unittest.TestCase):
    def test_already_vertical_source_skips_face_analysis_and_extra_encode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "portrait.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=size=360x640:rate=1",
                "-frames:v", "1", str(source),
            ], check=True)
            with (
                patch.object(framing, "analyse_faces", side_effect=AssertionError("unexpected face analysis")),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                output, face_info = framing.reframe_to_vertical(source, root)
            self.assertEqual(output, source)
            self.assertIsNone(face_info)

    def test_center_crop_accepts_narrow_portrait_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "portrait.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=size=100x300:rate=1",
                "-frames:v", "1", str(source),
            ], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                result = _reframe_center_crop(source, root)
            self.assertTrue(result.is_file())

    def test_local_source_is_read_without_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            args = parse_args([str(source), "--output", str(root / "output"),
                               "--no-transcribe", "--no-vertical"])
            with (
                patch.object(pipeline, "_run_uniform", return_value=0) as process,
                patch.object(pipeline.shutil, "copy2") as copy,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                pipeline.run(args)
            self.assertEqual(process.call_args.args[1], source)
            copy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
