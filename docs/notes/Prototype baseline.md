# Prototype baseline

Status: code reading only, not yet validated at runtime.

Source: [prototype/yt_clip_processor_prototype.py](../../prototype/yt_clip_processor_prototype.py)

## Observed pipeline

The prototype accepts a YouTube URL or local video path. Its normal path
optionally trims the source, reframes to vertical video, transcribes speech,
burns subtitles, and cuts uniform length clips. Hook mode transcribes first,
scores candidate openings, then processes selected segments as clips.

The CLI also exposes controls for clip length, Whisper model, subtitle timing,
scene types, titles, and intermediate file handling. It uses yt-dlp, ffmpeg,
faster-whisper, and MediaPipe; some paths use OpenCV and optional Groq titles.

## Questions before specifying improvements

- Which output quality problems matter most to the intended user?
- Which input types and platforms must the improved program support?
- What sample videos and measurable checks will show an improvement?
- Which current behaviors are deliberate and which are prototype shortcuts?

Record findings in an investigation note and turn agreed behavior into an
OpenSpec change. Avoid treating this code inventory as a feature contract.
