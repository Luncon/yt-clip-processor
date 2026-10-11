# yt-clip-processor

Turn a local video or a YouTube video into short clips. The maintained source
is in [`src/yt_clip_processor/`](src/yt_clip_processor/). The original
[`prototype/yt_clip_processor_prototype.py`](prototype/yt_clip_processor_prototype.py)
is retained for comparison and has not been edited.

## Install

Python 3.10 or newer, `ffmpeg`, and `ffprobe` are required. Install only the
extras needed for your workflow:

```sh
python -m pip install -e .                    # local video, no transcription or reframing
python -m pip install -e '.[all]'            # full YouTube, transcription, and framing workflow
```

`youtube`, `transcription`, `framing`, and `titles` are also available as
separate extras. The first vertical run downloads a MediaPipe face model.
Setting `GROQ_API_KEY` enables optional generated clip titles; otherwise
titles use transcript text.

## Use

```sh
yt-clip-processor ./video.mp4 --no-transcribe --no-vertical --clip-length 60
yt-clip-processor 'https://youtu.be/dQw4w9WgXcQ' --hooks 5 --hook-clip-length 90
yt-clip-processor ./video.mp4 --output ./output --start 60 --end 180
```

Uniform mode cuts consecutive clips. `--hooks N` transcribes the source and
selects up to N candidate moments before rendering them. Run
`yt-clip-processor --help` for the full option list.

Local inputs are read in place. Uniform clips with subtitles are cut and
subtitled in one final encode per clip after any vertical reframing.

Completed clips go to `output/clips/<run-id>/` by default. Working files live
in `output/.work/` and are removed after a run. Downloaded videos are cached
in `output/_cache/`; `--fresh` bypasses that cache for the current run without
deleting other output files. `--keep-original` also saves a copy of a downloaded
source in `output/originals/<run-id>/`.

## Check the package

```sh
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m yt_clip_processor --help
```

The tests include a small local video generated with ffmpeg when it is
available. Processing with Whisper, MediaPipe, or YouTube still requires a
representative manual run with those dependencies installed.

Project notes and the notes-to-specification workflow are in
[`docs/notes/README.md`](docs/notes/README.md). OpenSpec changes live in
`openspec/changes/`; durable capability specifications live in
`openspec/specs/`.
