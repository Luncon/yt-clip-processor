# Context-aware framing investigation

The October 11 Hasan Piker source `6utv1T5DBPI` is a browser/screen capture. At 03:00 and 20:00, the useful content occupies the left portion, chat occupies a right column, and the host camera sits in the lower right. The current reaction renderer takes a fixed center crop for content, which can omit the left side of the screen capture or useful text. The source is cached under `output/_cache/6utv1T5DBPI/` in the auto clip worktree.

The current detector returns at most two faces, classifies two faces as dual before considering a corner host camera, and anchors dual crops at the first matching keyframe for an entire mode run. Mode runs do not break on a camera cut when the mode stays the same. These are concrete failure paths to test; this note does not assert that every output clip exhibits them.

After the changes, local 12-second and 8-second excerpts beginning at 03:00 and 20:00 were rendered through the MediaPipe/OpenCV path. Both classified as `screen` from the first sample. Visual checks found the main content above the host camera; the 20:00 browser text remains visible but small because the whole content region is fitted to portrait width. The sample renders are under `output/diagnostics/context-framing-sample/` in the repository and are not committed test fixtures.

See [context-aware-reframing](../../openspec/changes/context-aware-reframing/proposal.md) for the proposed behavior.
