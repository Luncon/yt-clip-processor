# Design

## Context

The scene renderer currently locks each dual crop to one source half and fits an entire landscape wide frame inside a portrait canvas. See the proposal and spec for the requested outcomes.

## Goals / Non-Goals

**Goals:** Preserve face context at the dual split boundary and make wide content easier to see without changing the 9:16 output size.

**Non-Goals:** Change scene classification, face detection, single-face tracking, or reaction mode.

## Decisions

- Expand the dual crop modestly around each detected face and permit crops to overlap across the source midpoint. Keep each anchor fixed for its scene to avoid jitter. The output pane keeps the existing aspect ratio; a full-frame letterbox would shrink faces and defeat the request.
- Render wide frames with a centered crop at 70% of portrait output height. This leaves some top and bottom breathing room while using substantially more of the canvas than full-frame fitting. Filling all 9:16 pixels would discard too much of a 16:9 shot.
- Keep the layout math in small helpers so image-level tests can verify geometry without transcoding a video.

## Risks / Trade-offs

- A dual crop may include some of the other speaker near the midpoint; overlap is preferable to cutting off a profile.
- A centered wide crop discards outer edges of a landscape scene; full-frame context is no longer guaranteed in wide mode. This follows the requested visual priority.
