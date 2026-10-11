# Debate scene transition test

## Source and method

- Source: [ABC News, Presidential debate highlights from Trump and Harris's first showdown of 2024](https://www.youtube.com/watch?v=4aw5FziSc14).
- Tested the first 72 seconds at 1280 × 720, 29.97 fps. The source and output are local test artifacts under `/tmp/`; the footage is not committed to the repository.
- Ran the MediaPipe face analysis and vertical renderer, then compared source and output frames at 5, 10, 18, 25, 38, 46, 55, and 62 seconds.
- Ran the public CLI with `base.en` Whisper transcription, MediaPipe detection, vertical rendering, subtitle burning, and clip cutting. It produced one 72-second 720 × 1280 clip with audio and 184 transcribed words under `/tmp/ytcp_debate_cli/clips/`.
- Checked a second 20-second section starting at 8:40 in the source, containing close debate faces, a wide stage shot with no discernible faces, and a moderator close-up. The renderer switched dual → wide → single → wide; visual checks at 3, 9, 16, and 19 seconds of that section matched those layouts.
- Ran the full repository test suite after the change: 20 tests passed.

## Findings

The original renderer found 39 two-face, 16 one-face, and 20 zero-face samples in its one-second keyframe pass. It switched into split screen for sustained two-face shots and tracked a single speaker, but treated zero-face shots as single. At 10 seconds, the output centered an empty podium and lost both people. At 38 seconds, it showed mostly the backdrop rather than the full stage. At 5 seconds, low-confidence false face detections also caused a crop of a wide stage shot.

The renderer now classifies a sustained zero-face run as `wide` and fits the entire landscape frame inside the vertical canvas. Two consecutive empty samples confirm a wide shot; the resulting layout begins at the first sample of that run. A single missed detection does not trigger a layout change. The minimum detector confidence is now 0.60; this removed the stage false positives around 5 seconds without reducing the 39 two-face samples. Confirmed transitions back to a face layout also start at the first sampled frame of the face run. Split and single modes remain available for the other scenes.

The final scene timeline is single 0–3.9 s, wide 3.9–17.4 s, single 17.4–22.3 s, dual 22.3–36.8 s, wide 36.8–39.7 s, dual 39.7–42.6 s, wide 42.6–47.4 s, single 47.4–52.3 s, dual 52.3–59.0 s, single 59.0–60.0 s, and dual 60.0–72.0 s. Visual inspection at the sampled times confirmed full-stage, one-speaker, and two-speaker layouts.

## Limits

Face count means MediaPipe detections, not a manual count of all people in a frame. People in distant stage shots can be visible but too small for the detector. A full-frame wide shot uses letterboxing, which preserves information but makes the source smaller in a vertical video. This test does not cover reaction-camera overlays.
