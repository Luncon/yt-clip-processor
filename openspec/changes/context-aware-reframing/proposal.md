# Proposal

## Why

Face-only framing can mistake a screen capture with a corner webcam for a two-person interview, cut off content at panel boundaries, and hold a stale crop across camera cuts. Hasan Piker's `FRANCE IS ON FIRE AGAIN` source shows the screen, chat, and host camera arrangement motivating the change; see [the investigation](../../../docs/notes/Context-aware%20framing%20investigation.md).

## What Changes

- Detect stable visual panels and camera cuts before choosing portrait crops.
- Add a screen capture layout that keeps the content region readable and the corner speaker camera visible.
- Track faces within their panel and use audio speech timing plus visible mouth motion to favor the likely speaker only when confidence is sufficient.
- Validate sampled face coverage for planned crops and use a wider safe layout when a crop would cut a visible face.
- Retain the existing portrait output and conservative fallback for unrecognized layouts.

## Capabilities

### New Capabilities

- `scene-framing`: Choose and render portrait layouts for interviews, news panels, and screen captures while preserving speakers and important content.

### Modified Capabilities

None; the existing `scene-framing` delta has not been archived into the main specs.

## Impact

Face analysis, scene segmentation, rendering, and hook segment orchestration change. OpenCV, MediaPipe, and ffmpeg remain the media dependencies. No new API key is required.
