import json
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from yt_clip_processor.monitor import YouTubeClient, load_sources, open_database, poll, report


def video(views=None):
    statistics = {} if views is None else {"viewCount": str(views), "likeCount": "8"}
    return {"id": "abc12345678", "snippet": {"title": "Interview",
            "publishedAt": "2026-10-11T12:00:00Z"},
            "contentDetails": {"duration": "PT20M"}, "statistics": statistics}


class FakeClient:
    def __init__(self):
        self.views = 100

    def recent_videos(self, handle, limit):
        assert handle == "@Example"
        assert limit == 25
        return {"id": "channel-id"}, [video(self.views)]


class MonitorTests(unittest.TestCase):
    def test_api_key_is_sent_in_header_not_url(self):
        client = YouTubeClient("private-key")
        with patch("yt_clip_processor.monitor.urlopen", return_value=io.BytesIO(b'{"items": []}')) as open_url:
            self.assertEqual(client._get("channels", part="snippet"), {"items": []})
        request = open_url.call_args.args[0]
        self.assertNotIn("private-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "private-key")

    def test_youtube_client_uses_uploads_playlist_and_fetches_statistics(self):
        client = YouTubeClient("unused")
        calls = []

        def get(resource, **params):
            calls.append((resource, params))
            if resource == "channels":
                return {"items": [{"id": "channel-id", "contentDetails":
                        {"relatedPlaylists": {"uploads": "uploads-id"}}}]}
            if resource == "playlistItems":
                return {"items": [{"contentDetails": {"videoId": "abc12345678"}}]}
            return {"items": [video(100)]}

        client._get = get
        channel, videos = client.recent_videos("@Example", 25)
        self.assertEqual(channel["id"], "channel-id")
        self.assertEqual(videos[0]["statistics"]["viewCount"], "100")
        self.assertEqual(calls, [
            ("channels", {"part": "snippet,contentDetails", "forHandle": "@Example"}),
            ("playlistItems", {"part": "contentDetails", "playlistId": "uploads-id",
                               "maxResults": 25}),
            ("videos", {"part": "snippet,statistics,contentDetails", "id": "abc12345678"}),
        ])

    def test_poll_preserves_observations_and_reports_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            db = open_database(Path(directory) / "monitor.sqlite3")
            client = FakeClient()
            sources = [{"name": "Example", "handle": "@Example"}]
            first = datetime(2026, 10, 11, 13, tzinfo=timezone.utc).isoformat()
            second = datetime(2026, 10, 11, 15, tzinfo=timezone.utc).isoformat()
            self.assertEqual(poll(db, client, sources, first), 1)
            self.assertIsNone(report(db)[0]["view_growth_per_hour"])
            client.views = 300
            self.assertEqual(poll(db, client, sources, second), 1)
            self.assertEqual(poll(db, client, sources, second), 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
            self.assertEqual(report(db)[0]["view_growth_per_hour"], 100)
            self.assertEqual(report(db)[0]["age_hours"], 3)
            db.close()

    def test_missing_statistics_are_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            db = open_database(Path(directory) / "monitor.sqlite3")
            client = FakeClient()
            client.views = None
            poll(db, client, [{"name": "Example", "handle": "@Example"}],
                 datetime(2026, 10, 11, 13, tzinfo=timezone.utc).isoformat())
            item = report(db)[0]
            self.assertIsNone(item["views"])
            self.assertIsNone(item["likes"])
            self.assertIsNone(item["view_growth_per_hour"])
            db.close()

    def test_sources_config_and_missing_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "sources.json"
            config.write_text(json.dumps([{"name": "Example", "handle": "@Example"}]))
            self.assertEqual(load_sources(config), [{"name": "Example", "handle": "@Example"}])
        client = YouTubeClient("unused")
        client._get = lambda *args, **kwargs: {"items": []}
        with self.assertRaisesRegex(ValueError, "No YouTube channel found"):
            client.recent_videos("@Missing", 25)


if __name__ == "__main__":
    unittest.main()
