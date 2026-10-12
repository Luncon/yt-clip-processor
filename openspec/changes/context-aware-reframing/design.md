# Design

## Context

See proposal.md and the linked Hasan frame investigation. Face sampling already runs roughly once per second, mode hysteresis exists, and the renderer uses fixed dual/reaction anchors. The source may have no transcript when `--no-transcribe` is selected.

## Goals / Non-Goals

**Goals:** Keep scene analysis cheap relative to video rendering, make layouts stable across frames, preserve the 9:16 output, and use existing media dependencies.

**Non-Goals:** Perfect speaker diarization, OCR of every graphic, reconstruction of pixels obscured by overlays, or a new cloud model requirement.

## Decisions

- Detect high-confidence straight panel dividers on sampled frames before interpreting face counts. A divider requires a persistent edge across a substantial portion of a row or column; ordinary profile contours do not qualify. Face crops are clamped to panels when safe. This is simpler and easier to validate than a generic segmentation model.
- Detect substantial visual changes between sampled frames and split scenes on those cuts even when the mode stays the same. Rebuild anchors per shot. An exact video edit list is unnecessary for this purpose.
- Classify a sustained small corner face over a content region as `screen` before ordinary dual mode, even if the screen region contains another face. Extract the principal screen area from the side opposite a chat divider when possible; otherwise show the full source as content. Render content above a smaller camera pane with contain scaling over a blurred fill to preserve text and edge information.
- Use transcript word times as a speech gate when available and a cheap mouth-region motion estimate for the face choice. Require repeated, clearly separated motion scores before changing prominence. Without reliable evidence, keep equal-size dual panes. Audio voice identity is not inferred from word times alone.
- Build dual crop bounds from all sampled faces in each scene and check containment with margin. If the crop cannot include a face within its panel, use a wider panel fit rather than silently clipping it.

## Risks / Trade-offs

- Straight divider detection misses irregular or animated layouts → use the current face-based or safe wide fallback.
- Motion can come from head movement or video playback → require sustained evidence and keep equal panes when uncertain.
- Screen fitting makes text smaller than aggressive cropping → prefer complete information over an unreadable partial chart; blurred fill avoids large black voids.
- Source overlays can obscure content permanently → no automatic crop can restore hidden pixels.
