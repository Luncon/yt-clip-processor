# Tasks

## 1. Package foundation

- [x] 1.1 Add installable package and console entry point; verify module import and `--help`.
- [x] 1.2 Move media, source, transcript, framing, subtitle, title, and hook functions into stage modules; verify imports and compile all source files.

## 2. Pipeline behavior

- [x] 2.1 Move normal and hook orchestration into a pipeline module; verify both paths through focused tests.
- [x] 2.2 Validate numeric and incompatible CLI options, including fresh output safety; verify regression tests.
- [x] 2.3 Require only dependencies used by the selected run and handle silent media where supported; verify tests.

## 3. Integration and documentation

- [x] 3.1 Run an ffmpeg generated local media smoke test for the new CLI and inspect its output.
- [x] 3.2 Document installation, both CLI paths, and output ownership in README; verify commands match the package.
- [x] 3.3 Run full tests, OpenSpec validation, and record the unchanged prototype source checksum.

## 4. Review fixes

- [x] 4.1 Keep normalized topic tokens through hook diversity selection and cover repeated distant topics.
- [x] 4.2 Index transcript and face timestamps once per hook ranking run.
- [x] 4.3 Support narrow portrait media in the center-crop fallback and avoid duplicating local sources.
- [x] 4.4 Burn subtitles directly into final uniform clips with clip-relative timing; verify visible text in each output clip.
- [x] 4.5 Run real Whisper and MediaPipe inference in uniform and hook modes; fix the discovered PyAV decoding failure and verify media streams and visible subtitles.

## Workflow follow-up

- Archive the change after review.
