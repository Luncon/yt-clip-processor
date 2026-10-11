# Proposal

## Why

The existing processor is a single large prototype with coupled pipeline stages and limited validation. Users need a maintainable source package that keeps the current clip workflow while making failures and output handling predictable. The code review is recorded in the preceding conversation; the [baseline note](../../../docs/notes/Prototype%20baseline.md) is a code inventory, not a requirement.

## What Changes

- Add an installable Python package and CLI beside the unchanged prototype.
- Separate source acquisition, media operations, transcription, framing, subtitles, titles, hook selection, and orchestration.
- Validate CLI inputs, make dependency checks conditional, and confine cleanup to program owned files.
- Add tests for pure behavior and a small local media integration path.

## Capabilities

### New Capabilities

- `video-processing`: CLI input handling, output safety, and uniform or hook based clip generation.

### Modified Capabilities

None.

## Impact

New `src/yt_clip_processor/` package, packaging metadata, tests, and README. The prototype remains untouched. Existing external tools and optional services remain dependencies of the respective processing paths.
