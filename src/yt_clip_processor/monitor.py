"""Collect public YouTube upload statistics for source selection."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_SOURCES = (
    {"name": "Tucker Carlson", "handle": "@TuckerCarlson"},
    {"name": "Candace Owens", "handle": "@RealCandaceO"},
    {"name": "Hasan Piker", "handle": "@HasanAbi"},
    {"name": "Fox News", "handle": "@FoxNews"},
)
API_ROOT = "https://www.googleapis.com/youtube/v3"


class YouTubeClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def _get(self, resource, **params):
        query = urlencode(params)
        request = Request(f"{API_ROOT}/{resource}?{query}",
                          headers={"x-goog-api-key": self.api_key})
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"YouTube API {resource} request failed (HTTP {exc.code})") from None
        except URLError as exc:
            raise RuntimeError(f"YouTube API {resource} request failed: {exc.reason}") from None

    def recent_videos(self, handle, limit):
        channels = self._get("channels", part="snippet,contentDetails", forHandle=handle)
        if not channels.get("items"):
            raise ValueError(f"No YouTube channel found for {handle}")
        channel = channels["items"][0]
        playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        items = self._get("playlistItems", part="contentDetails", playlistId=playlist,
                          maxResults=limit).get("items", [])
        ids = [item["contentDetails"]["videoId"] for item in items]
        if not ids:
            return channel, []
        videos = self._get("videos", part="snippet,statistics,contentDetails",
                           id=",".join(ids)).get("items", [])
        return channel, videos


def load_sources(path):
    sources = json.loads(path.read_text(encoding="utf-8")) if path else DEFAULT_SOURCES
    if not isinstance(sources, (list, tuple)) or not sources:
        raise ValueError("source configuration must be a nonempty JSON array")
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("name"), str)
                or not isinstance(source.get("handle"), str)
                or not source["name"].strip() or not source["handle"].startswith("@")):
            raise ValueError("each source needs a name and a YouTube @handle")
    return sources


def open_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT NOT NULL,
            duration TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL REFERENCES videos(video_id),
            observed_at TEXT NOT NULL,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            UNIQUE(video_id, observed_at)
        );
    """)
    return db


def _public_count(statistics, name):
    value = statistics.get(name)
    return int(value) if value is not None else None


def poll(db, client, sources, observed_at, limit=25):
    """Fetch all sources before writing, so an API failure leaves this poll unchanged."""
    pending = []
    for source in sources:
        channel, videos = client.recent_videos(source["handle"], limit)
        for video in videos:
            snippet = video["snippet"]
            stats = video.get("statistics", {})
            pending.append((video["id"], source["name"], channel["id"],
                            snippet["title"], snippet["publishedAt"],
                            video["contentDetails"]["duration"],
                            observed_at, _public_count(stats, "viewCount"),
                            _public_count(stats, "likeCount"),
                            _public_count(stats, "commentCount")))
    with db:
        for row in pending:
            db.execute("""
                INSERT INTO videos VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    source_name=excluded.source_name,
                    channel_id=excluded.channel_id,
                    title=excluded.title,
                    published_at=excluded.published_at,
                    duration=excluded.duration
            """, row[:6])
            db.execute("""
                INSERT INTO observations (video_id, observed_at, views, likes, comments)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(video_id, observed_at) DO UPDATE SET
                    views=excluded.views, likes=excluded.likes, comments=excluded.comments
            """, (row[0], *row[6:]))
    return len(pending)


def report(db, limit=100):
    rows = db.execute("""
        SELECT v.video_id, v.source_name, v.title, v.published_at,
               o.observed_at, o.views, o.likes, o.comments
        FROM videos v JOIN observations o ON o.video_id = v.video_id
        WHERE o.id = (SELECT MAX(o2.id) FROM observations o2 WHERE o2.video_id = v.video_id)
        ORDER BY v.published_at DESC LIMIT ?
    """, (limit,)).fetchall()
    result = []
    for video_id, source, title, published, observed, views, likes, comments in rows:
        age_hours = (datetime.fromisoformat(observed) -
                     datetime.fromisoformat(published.replace("Z", "+00:00"))).total_seconds() / 3600
        previous = db.execute("""
            SELECT observed_at, views FROM observations
            WHERE video_id = ? AND observed_at < ?
            ORDER BY observed_at DESC LIMIT 1
        """, (video_id, observed)).fetchone()
        hourly_growth = None
        if previous and previous[1] is not None and views is not None:
            hours = (datetime.fromisoformat(observed) -
                     datetime.fromisoformat(previous[0])).total_seconds() / 3600
            if hours > 0:
                hourly_growth = (views - previous[1]) / hours
        result.append({"source": source, "title": title, "published_at": published,
                       "url": f"https://www.youtube.com/watch?v={video_id}",
                       "age_hours": max(0, age_hours),
                       "views": views, "likes": likes, "comments": comments,
                       "view_growth_per_hour": hourly_growth})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Monitor YouTube source performance")
    parser.add_argument("--sources", type=Path, help="JSON file of name and @handle pairs")
    parser.add_argument("--db", type=Path, default=Path("output/source-monitor.sqlite3"))
    parser.add_argument("--max-videos", type=int, default=25,
                        help="Recent uploads to inspect per channel (1-50, default: 25)")
    parser.add_argument("--report-only", action="store_true", help="Show saved data without polling")
    args = parser.parse_args(argv)
    if not 1 <= args.max_videos <= 50:
        parser.error("--max-videos must be between 1 and 50")
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not args.report_only and not api_key:
        parser.error("set YOUTUBE_API_KEY to poll YouTube, or use --report-only")
    try:
        sources = load_sources(args.sources)
        db = open_database(args.db)
        try:
            if not args.report_only:
                count = poll(db, YouTubeClient(api_key), sources,
                             datetime.now(timezone.utc).isoformat(), args.max_videos)
                print(f"Saved observations for {count} videos.")
            for item in report(db):
                growth = item["view_growth_per_hour"]
                growth_label = "n/a" if growth is None else f"{growth:+,.0f}/hour"
                views = "n/a" if item["views"] is None else f"{item['views']:,}"
                print(f"{item['source']} | {item['age_hours']:.0f}h old | "
                      f"{views} views | {growth_label} | {item['title']}")
                print(f"  {item['url']}")
        finally:
            db.close()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
