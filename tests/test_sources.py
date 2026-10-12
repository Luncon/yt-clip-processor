"""YouTube downloads must contain the streams needed by the pipeline."""

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.sources import download_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
class DownloadTests(unittest.TestCase):
    def test_video_only_cache_is_not_used_and_merged_download_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "_cache" / "6utv1T5DBPI"
            cache.mkdir(parents=True)
            fragment = cache / "interview.f299.mp4"
            merged = cache / "interview.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=size=32x32:rate=1:duration=1",
                "-c:v", "mpeg4", str(fragment),
            ], check=True)

            class FakeYoutubeDL:
                def __init__(self, options):
                    self.options = options

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, url, download):
                    self_test.assertTrue(download)
                    subprocess.run([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=size=32x32:rate=1:duration=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(merged),
                    ], check=True)
                    return {"id": "6utv1T5DBPI"}

                def prepare_filename(self, info):
                    return str(fragment)

            self_test = self
            with (patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)}),
                  contextlib.redirect_stdout(io.StringIO())):
                result = download_video("https://youtu.be/6utv1T5DBPI", root, root)

            self.assertEqual(result, merged)


if __name__ == "__main__":
    unittest.main()
