"""A small local media check for the dependency-free processing path."""

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

from yt_clip_processor.cli import main
from yt_clip_processor import pipeline
from yt_clip_processor.cli import parse_args


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
class LocalPipelineTests(unittest.TestCase):
    @staticmethod
    def make_video(path):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=160x90:rate=10", "-t", "2", "-c:v", "libx264",
             str(path)],
            check=True,
        )

    def test_fresh_local_run_preserves_unrelated_files_and_writes_clips(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "output"
            output.mkdir()
            unrelated = output / "my-notes.txt"
            unrelated.write_text("keep this")
            self.make_video(source)

            with contextlib.redirect_stdout(io.StringIO()):
                main([str(source), "--output", str(output), "--clip-length", "1",
                      "--no-transcribe", "--no-vertical", "--fresh"])

            self.assertEqual(unrelated.read_text(), "keep this")
            clips = list((output / "clips").rglob("*.mp4"))
            self.assertEqual(len(clips), 2)
            for clip in clips:
                duration = subprocess.check_output([
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(clip),
                ], text=True)
                self.assertGreater(float(duration), 0.8)
            self.assertEqual(list((output / ".work").iterdir()), [])

    def test_keep_original_saves_download_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            self.make_video(source)
            output = root / "output"
            args = parse_args([
                "https://youtu.be/dQw4w9WgXcQ", "--output", str(output),
                "--no-transcribe", "--no-vertical", "--keep-original",
            ])

            def fake_download(url, work_dir, cache_root, fresh):
                downloaded = work_dir / "downloaded.mp4"
                shutil.copy2(source, downloaded)
                return downloaded

            with patch.object(pipeline, "download_video", side_effect=fake_download):
                with contextlib.redirect_stdout(io.StringIO()):
                    clips_dir = pipeline.run(args)

            self.assertEqual(len(list(clips_dir.glob("*.mp4"))), 1)
            self.assertEqual(len(list((output / "originals").rglob("*.mp4"))), 1)

    def test_uniform_subtitles_render_each_final_clip_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=10",
                "-t", "2", "-c:v", "libx264", str(source),
            ], check=True)
            output = root / "output"
            args = parse_args([
                str(source), "--output", str(output), "--clip-length", "1",
                "--no-vertical", "--no-llm-titles",
            ])
            words = [
                {"word": "first", "start": 0.1, "end": 0.5},
                {"word": "second", "start": 1.1, "end": 1.5},
            ]

            with (
                patch.object(pipeline, "transcribe_audio_only", return_value=words),
                patch.object(pipeline, "burn_subtitles", wraps=pipeline.burn_subtitles) as burn,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                clips_dir = pipeline.run(args)

            self.assertEqual(len(list(clips_dir.glob("*.mp4"))), 2)
            self.assertEqual(burn.call_count, 2)
            for clip in clips_dir.glob("*.mp4"):
                frame = subprocess.check_output([
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-ss", "0.3", "-i", str(clip), "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
                ])
                self.assertGreater(max(frame), 80, clip.name)

    def test_uniform_clip_seek_starts_at_requested_second(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "colors.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:size=160x90:rate=10:d=1",
                "-f", "lavfi", "-i", "color=c=blue:size=160x90:rate=10:d=1",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
                "-c:v", "libx264", str(source),
            ], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                main([str(source), "--output", str(root / "output"),
                      "--clip-length", "1", "--no-transcribe", "--no-vertical"])

            clips = sorted((root / "output" / "clips").rglob("*.mp4"))
            self.assertEqual(len(clips), 2)
            pixels = []
            for clip in clips:
                frame = subprocess.check_output([
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-ss", "0.5", "-i", str(clip), "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ])
                pixels.append(tuple(frame[:3]))
            self.assertGreater(pixels[0][0], pixels[0][2])
            self.assertGreater(pixels[1][2], pixels[1][0])


if __name__ == "__main__":
    unittest.main()
