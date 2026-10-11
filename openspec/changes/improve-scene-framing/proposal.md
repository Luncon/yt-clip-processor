# Proposal

## Why

Profile views in two-person scenes can clip a speaker at the split boundary, while wide landscape shots appear too small on a portrait canvas. This feedback was recorded in the [Jubilee scene framing note](../../../docs/notes/Jubilee%20scene%20framing%20feedback.md).

## What Changes

- Give each speaker more horizontal and vertical context in dual scenes, including room across the source midpoint.
- Show a larger centered view for wide shots while keeping the portrait output.
- Add focused image-level tests for both layouts.

## Capabilities

### New Capabilities

- `scene-framing`: Select and render portrait layouts for two-person and wide scenes.

### Modified Capabilities

None.

## Impact

Changes the scene-aware renderer and its tests. No CLI flags or dependencies change.
