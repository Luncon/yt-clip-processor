# Design

## Context

The prototype is a single 3,775-line script. Its functional areas are identifiable, but orchestration, filesystem effects, and media operations share module state. See [proposal.md](proposal.md) for motivation.

## Goals / Non-Goals

**Goals:** An independently runnable source package, clear stage boundaries, small testable functions, and safe output ownership.

**Non-Goals:** Retuning hook weights, changing visual style, or deleting the prototype.

## Decisions

- Use a `src/` Python package with a console entry point. This avoids importing the prototype at runtime and permits package tests; a thin wrapper around the prototype would preserve its coupling.
- Separate modules by stage: source acquisition, media tools, transcription, framing, subtitles, hook ranking, titles, and pipeline/CLI orchestration. Keep existing algorithms during the move so behavior changes can be reviewed separately.
- Validate arguments before dependency checks or filesystem writes. Use run-specific working directories and explicit ownership for cleanup instead of sweeping the output root.
- Keep external media and model imports inside the stage that needs them, allowing light CLI and unit tests without those packages.
- Exercise pure ranking and option logic with unit tests, plus a tiny generated local media fixture for an end-to-end path when ffmpeg is available.

## Risks / Trade-offs

- Moving tightly coupled functions can miss implicit globals → use import and compilation checks plus targeted tests.
- Video output may differ across codecs and platforms → keep a documented local smoke path; do not claim bit-for-bit parity.
- Existing heuristic scoring has no labeled benchmark → preserve it during this change and evaluate separately.

## Migration Plan

Add the package beside `prototype/`, document the new invocation, and leave the prototype available for comparison. Revert by returning to the prototype entry point; no data migration is needed.

## Post-review decisions

- Hook diversity must retain each accepted candidate's normalized tokens until all candidates have been compared. Transcript and face windows use sorted timestamp indexes so long recordings do not trigger a full scan for every candidate.
- Local source paths are read directly. Trimming and rendering still write to run-owned paths, and cleanup remains limited to the work directory.
- Uniform subtitles are generated on each final clip with clip-relative timestamps. An input seek places the cut before decoding, while the subtitle filter and final encode run together. This removes the full-video subtitle encode and the later clip re-encode.
- A scale-then-crop fallback supports source aspect ratios on either side of 9:16.
- Transcribe the trimmed source audio before reframing. Whisper receives the already normalized PCM chunk as a NumPy waveform, avoiding a second decode and the incompatible PyAV 19 file-decoding path in faster-whisper 1.2.1.
