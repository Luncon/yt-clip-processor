## Design

Use the YouTube Data API `channels.list(forHandle)` to resolve each configured channel and its uploads playlist, `playlistItems.list` to find recent uploads, and `videos.list` to fetch duration and statistics. Avoid `search.list` for recent uploads. Store video identity and immutable observations in SQLite under `output/` by default. A standalone CLI keeps monitoring independent from the rendering pipeline.

The report shows each video's latest views, age, and view growth per hour between its two newest observations. An initial observation has no growth rate. Missing public statistics remain unknown rather than zero. This is an evidence collection step; cross-channel ranking and posting decisions need a fuller age-matched baseline.

Source handles are defaults and can be overridden through a JSON configuration file. Resolve handles on each run so the API verifies them; surface missing channels clearly. Never store the API key.
