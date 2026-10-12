# Source performance pilot

The first source monitor observes the public YouTube uploads for Tucker
Carlson, Candace Owens, HasanAbi, and Fox News. Andrew Wilson was removed from
the pilot at the user's request.

The initial metric is the change in public view count between polls, divided by
elapsed hours. A first run cannot produce that rate. We should compare videos
at similar ages within each channel after enough observations accumulate; raw
views across these four channels are not directly comparable. Later work can
link the chosen source video to clip decisions and TikTok outcomes.

The implementation is specified in
[`monitor-source-performance`](../../openspec/changes/monitor-source-performance/proposal.md).
