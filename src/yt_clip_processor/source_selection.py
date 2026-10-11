"""Choose an eligible source video from saved monitor observations."""

import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from .monitor import report


_DURATION = re.compile(r"^P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def _duration_seconds(value):
    match = _DURATION.fullmatch(value)
    if not match:
        return 0
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def choose_monitored_source(db_path: Path, clip_length: int, count: int, now=None):
    """Return URL and evidence for the strongest recent eligible upload."""
    if not db_path.is_file():
        raise ValueError(f"monitor database not found: {db_path}; poll with yt-clip-monitor first")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"monitor database is unreadable: {db_path}") from exc
    try:
        observations = report(db, limit=1000)
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"monitor database is unreadable: {db_path}") from exc
    finally:
        db.close()

    now = now or datetime.now(timezone.utc)
    minimum_duration = max(360, int(clip_length * count * 1.2))
    eligible = [item for item in observations
                if 0 <= (now - datetime.fromisoformat(
                    item["published_at"].replace("Z", "+00:00"))).total_seconds() <= 72 * 3600
                and 0 <= (now - datetime.fromisoformat(
                    item["observed_at"])).total_seconds() <= 12 * 3600
                and _duration_seconds(item["duration"]) >= minimum_duration
                and item["view_growth_per_hour"] is not None
                and item["view_growth_per_hour"] > 0]
    if not eligible:
        raise ValueError("no recent, rising monitored video is long enough; "
                         "poll the monitor again later or provide a video URL")

    by_source = {}
    for item in eligible:
        by_source.setdefault(item["source"], []).append(item["view_growth_per_hour"])

    def rank(item):
        growth = item["view_growth_per_hour"]
        peers = by_source[item["source"]]
        baseline = median(peers) if len(peers) >= 3 else None
        relative = growth / baseline if baseline and baseline > 0 else 1.0
        return min(relative, 10.0) * math.log1p(growth)

    selected = max(eligible, key=lambda item: (rank(item), item["published_at"]))
    peers = by_source[selected["source"]]
    baseline = median(peers) if len(peers) >= 3 else None
    growth = selected["view_growth_per_hour"]
    reason = f"{growth:,.0f} new views/hour over the latest two polls"
    if baseline and baseline > 0:
        reason += f"; {growth / baseline:.1f}x this source's recent median"
    return {"url": selected["url"], "source": selected["source"],
            "title": selected["title"], "video_id": selected["video_id"],
            "view_growth_per_hour": growth, "reason": reason,
            "minimum_duration_seconds": minimum_duration}
