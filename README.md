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

## Run from this repository

Use this repository folder for both monitoring and processing. With the local
virtual environment activated, these commands work without installing the
package:

```sh
source venv/bin/activate
PYTHONPATH=src python -m yt_clip_processor.monitor
PYTHONPATH=src python -m yt_clip_processor --from-monitor \
  --auto-clips 4 --auto-clip-length 60
```

The monitor database is `output/source-monitor.sqlite3`, downloaded sources
are in `output/_cache/`, and completed clips are in `output/clips/`. Existing
data from the earlier temporary worktrees has been consolidated here. Framing
test videos are in `output/diagnostics/context-framing-sample/`. All `output/`
contents stay local and are ignored by Git.

## Use

```sh
yt-clip-processor ./video.mp4 --no-transcribe --no-vertical --clip-length 60
yt-clip-processor 'https://youtu.be/dQw4w9WgXcQ' --hooks 5 --hook-clip-length 90
yt-clip-processor ./video.mp4 --output ./output --start 60 --end 180
```

Uniform mode cuts consecutive clips. `--hooks N` transcribes the source and
selects up to N candidate moments before rendering them. Run
`yt-clip-processor --help` for the full option list.

For automatic selection without a review queue, use `--auto-clips` with a
target length. The selector searches the full transcript for complete spoken
windows, rejects sponsor reads and weak fragments, and renders up to the
requested count. `--hooks` remains an alias for the new selector.
If `GROQ_API_KEY` is set, it also assesses the meaning of shortlisted
transcripts before ranking; if that service fails, local scores still work.
Use `--no-semantic-rank` to keep selection local. Semantic ranking sends up to
48 candidate transcripts to Groq and may use paid API quota.

```sh
yt-clip-processor 'https://www.youtube.com/watch?v=VIDEO_ID' --auto-clips 4 --auto-clip-length 60
```

To choose the source video automatically, poll the source monitor at least
twice, then point the processor at its database:

```sh
yt-clip-processor --from-monitor --monitor-db output/source-monitor.sqlite3 \
  --auto-clips 4 --auto-clip-length 60
```

The selected upload must be recent, rising, and long enough for the requested
clips. If none qualifies, the run stops before downloading media. Each
automatic run writes `selection.json` beside its clips with source and clip
reasons, timestamps, scores, and render outcomes. Scores are transcript-based
predictions, not measured short-form performance. Use `--min-auto-score` to
adjust the quality threshold; the default is 65.

Vertical framing uses separate top and bottom panes for sustained two-person
shots, with room around each face for profile views. It detects straight panel
dividers and camera cuts so crops stay with the right panel and reset when the
shot changes. When speech timing and repeated mouth movement clearly indicate
one speaker, that pane grows slightly; uncertain shots keep equal panes.
Screen captures with a small lower-corner camera use a content pane above a
smaller camera pane, preserving the screen region beside chat when detected.
The screen is fitted whole over a soft background, so dense text may still be
small on a phone. Wide shots use a larger centered view of the source frame.

## Monitor source uploads

The pilot monitor follows Tucker Carlson, Candace Owens, Hasan Piker's
HasanAbi channel, and Fox News on YouTube. Create a YouTube Data API key, set
it locally, and run the monitor every few hours:

```sh
export YOUTUBE_API_KEY='your-key-here'
yt-clip-monitor
yt-clip-monitor --report-only
```

If the package is not installed, run
`PYTHONPATH=src python -m yt_clip_processor.monitor` from the repository root.
The monitor saves video
details and dated view, like, and comment counts in
`output/source-monitor.sqlite3` (ignored by Git). On the first run, view growth
is `n/a`; later runs show the difference in views per hour between the two most
recent observations. This is source evidence, not an automatic clip choice.

Use `--max-videos 50` to inspect more recent uploads per channel, `--db PATH`
to choose a database, or `--sources PATH` for a JSON array such as
`[{"name":"Example","handle":"@Example"}]`. The key is read only from the
environment and is not saved in the database. The monitor does not download
videos or publish clips.

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
