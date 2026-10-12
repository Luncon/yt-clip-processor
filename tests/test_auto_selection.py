"""Automatic candidate selection and monitored source regressions."""

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from yt_clip_processor.hooks import find_hook_clips
from yt_clip_processor.monitor import open_database, poll
from yt_clip_processor import semantic
from yt_clip_processor.source_selection import choose_monitored_source


def spoken_words(sentence, repeats=12, step=0.5):
    tokens = sentence.split()
    return [{"word": tokens[index % len(tokens)], "start": index * step,
             "end": index * step + step * 0.8}
            for index in range(len(tokens) * repeats)]


class CandidateSelectionTests(unittest.TestCase):
    def test_plain_language_can_be_selected_without_face_signal(self):
        words = spoken_words("We asked everyone what changed and found the answer together.",
                             repeats=14)
        clips = find_hook_clips(words, 3, 60, face_timestamps=set())
        self.assertTrue(clips)
        self.assertGreaterEqual(clips[0]["score"], 65)
        self.assertIn("ends on a sentence boundary", clips[0]["reasons"])

    def test_high_threshold_returns_no_weak_clip(self):
        words = spoken_words("We asked everyone what changed and found the answer together.",
                             repeats=14)
        self.assertEqual(find_hook_clips(words, 4, 60, min_score=100), [])

    def test_sponsor_read_is_excluded(self):
        words = spoken_words("This video is sponsored by our partner today.", repeats=20)
        self.assertEqual(find_hook_clips(words, 3, 60), [])

    def test_semantic_score_contributes_to_final_rank(self):
        words = spoken_words("We asked everyone what changed and found the answer together.",
                             repeats=14)
        clips = find_hook_clips(words, 1, 60, min_score=75,
                                semantic_scorer=lambda candidates: {0: (95, "clear insight")})
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["semantic_score"], 95)
        self.assertIn("semantic assessment: clear insight", clips[0]["reasons"])


class SemanticServiceTests(unittest.TestCase):
    def test_validates_model_scores_and_keeps_key_out_of_url(self):
        content = json.dumps({"items": [{"id": 0, "score": 88, "reason": "clear point"},
                                        {"id": 4, "score": 100, "reason": "wrong id"},
                                        {"id": 0, "score": 200, "reason": "bad score"}]})
        response = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        with patch.object(semantic, "urlopen", return_value=io.BytesIO(response)) as open_url:
            result = semantic._assess_batch([{"clip_text": "A complete point."}], "private-key")
        self.assertEqual(result, {0: (88, "clear point")})
        request = open_url.call_args.args[0]
        self.assertNotIn("private-key", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-key")

    def test_service_failure_uses_local_scores(self):
        with (patch.dict("os.environ", {"GROQ_API_KEY": "private-key"}),
              patch.object(semantic, "_assess_batch", side_effect=ValueError("invalid"))):
            with patch("builtins.print"):
                self.assertEqual(semantic.semantic_scores([{"clip_text": "Example"}]), {})


class SourceSelectionTests(unittest.TestCase):
    def test_chooses_rising_recent_long_video(self):
        class Client:
            views = 100

            def recent_videos(self, handle, limit):
                return {"id": "channel"}, [{"id": "abc12345678",
                    "snippet": {"title": "Long interview",
                                "publishedAt": "2026-10-11T12:00:00Z"},
                    "contentDetails": {"duration": "PT20M"},
                    "statistics": {"viewCount": str(self.views)}}]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.sqlite3"
            db = open_database(path)
            client = Client()
            sources = [{"name": "Example", "handle": "@Example"}]
            poll(db, client, sources, "2026-10-11T14:00:00+00:00")
            with self.assertRaisesRegex(ValueError, "no recent, rising"):
                choose_monitored_source(path, 60, 4,
                                        now=datetime(2026, 10, 11, 14, tzinfo=timezone.utc))
            client.views = 500
            poll(db, client, sources, "2026-10-11T15:00:00+00:00")
            db.close()
            now = datetime(2026, 10, 11, 16, tzinfo=timezone.utc)
            selected = choose_monitored_source(path, 60, 4, now=now)
            self.assertEqual(selected["url"], "https://www.youtube.com/watch?v=abc12345678")
            self.assertEqual(selected["view_growth_per_hour"], 400)
            with self.assertRaisesRegex(ValueError, "no recent, rising"):
                choose_monitored_source(path, 60, 4,
                                        now=datetime(2026, 10, 13, tzinfo=timezone.utc))

    def test_source_relative_growth_beats_large_channel_raw_growth(self):
        now = datetime(2026, 10, 11, 16, tzinfo=timezone.utc)
        common = {"duration": "PT20M", "published_at": "2026-10-11T12:00:00Z",
                  "observed_at": "2026-10-11T15:00:00+00:00"}
        rows = [
            {**common, "source": "Large", "video_id": f"large{i}",
             "url": f"https://youtu.be/large{i}", "title": "Large interview",
             "view_growth_per_hour": growth}
            for i, growth in enumerate((30000, 32000, 40000))
        ] + [
            {**common, "source": "Rising", "video_id": f"rising{i}",
             "url": f"https://youtu.be/rising{i}", "title": "Rising interview",
             "view_growth_per_hour": growth}
            for i, growth in enumerate((2000, 2200, 10000))
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.sqlite3"
            path.touch()
            with patch("yt_clip_processor.source_selection.report", return_value=rows):
                selected = choose_monitored_source(path, 60, 4, now=now)
        self.assertEqual(selected["source"], "Rising")
        self.assertIn("this source's recent median", selected["reason"])

    def test_missing_monitor_database_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "poll with yt-clip-monitor"):
                choose_monitored_source(Path(directory) / "missing.sqlite3", 60, 4)


if __name__ == "__main__":
    unittest.main()
