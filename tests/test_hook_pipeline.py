"""Hook orchestration without external models or a network download."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor import pipeline
from yt_clip_processor.cli import parse_args


class HookPipelineTests(unittest.TestCase):
    def test_no_candidate_writes_empty_selection_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            args = parse_args([str(source), "--output", str(root / "output"),
                               "--auto-clips", "4", "--no-vertical"])
            with (patch.object(pipeline, "transcribe_audio_only", return_value=[]),
                  patch.object(pipeline, "find_hook_clips", return_value=[]),
                  contextlib.redirect_stdout(io.StringIO())):
                clips_dir = pipeline.run(args)
            manifest = json.loads((clips_dir / "selection.json").read_text())
            self.assertEqual(manifest["clips"], [])
            self.assertEqual(manifest["requested_clips"], 4)

    def test_hook_run_writes_selected_clip_and_cleans_workdir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            output = root / "output"
            args = parse_args([
                str(source), "--output", str(output), "--hooks", "1",
                "--no-vertical", "--no-burn-subs", "--no-llm-titles",
            ])
            hook = {
                "start_sec": 0.0, "end_sec": 2.0, "hook_preview": "A clear opening",
                "signals": {}, "score": 80, "timestamp": "00:00:00",
            }

            def write_clip(**kwargs):
                kwargs["clip_path"].write_bytes(b"rendered clip")
                return True

            with (
                patch.object(pipeline, "transcribe_audio_only", return_value=[]),
                patch.object(pipeline, "find_hook_clips", return_value=[hook]),
                patch.object(pipeline, "_print_hook_summary"),
                patch.object(pipeline, "process_hook_segment", side_effect=write_clip),
                patch.object(pipeline, "generate_clip_title", return_value="title"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                clips_dir = pipeline.run(args)

            self.assertEqual((clips_dir / "01_title.mp4").read_bytes(), b"rendered clip")
            manifest = json.loads((clips_dir / "selection.json").read_text())
            self.assertEqual(manifest["clips"][0]["status"], "rendered")
            self.assertEqual(manifest["clips"][0]["start_sec"], 0.0)
            self.assertEqual(list((output / ".work").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
