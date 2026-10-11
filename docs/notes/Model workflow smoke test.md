# Model workflow smoke test — 2026-10-10

## Input

An 11-second local MP4 was assembled under `/tmp` from the [faster-whisper JFK speech fixture](https://github.com/SYSTRAN/faster-whisper/blob/master/tests/data/jfk.flac) and the [OpenCV face sample](https://github.com/opencv/opencv/blob/4.x/samples/data/lena.jpg). The image is static; this checks detection and rendering, not tracking a moving person. The cached `base.en` Whisper model and MediaPipe BlazeFace model were used with network access disabled during inference.

## Results

- Uniform mode: MediaPipe found one face in all 11 sampled frames; Whisper returned 22 words. The processor wrote two 1080×1920 clips with audio, visible karaoke subtitles, and durations of 6 and 5 seconds. Working files were removed.
- Hook mode: the face gate found a face in 11 of 11 samples. The ranker selected one 10-second clip; it has a 1080×1920 video stream, audio, and visible subtitles. Working files were removed.
- Extracted frames were inspected from both uniform clips and the hook clip. The face crop and text were visible. Audio starts at the same time as the source in both modes.

## Issue found and fixed

The first run failed when faster-whisper 1.2.1 passed `metadata_errors` to PyAV 19. PyAV 19 removed that argument; see the [PyAV release notes](https://github.com/PyAV-Org/PyAV/releases) and [faster-whisper issue](https://github.com/SYSTRAN/faster-whisper/issues/1589). The processor now loads its already extracted 16 kHz PCM chunks as float32 NumPy waveforms and passes them directly to Whisper. This also avoids decoding the chunk a second time. Uniform mode transcribes the trimmed source before reframing, so hook and uniform subtitle timelines use the same audio.

## Scope

This run exercised real Whisper and MediaPipe inference, single-face framing, hook face gating, subtitle rendering, audio, and output cleanup. It did not exercise YouTube downloading, moving-face tracking, dual/reaction layouts, or long-audio chunk boundaries.
