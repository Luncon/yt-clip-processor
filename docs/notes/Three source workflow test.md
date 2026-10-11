# Three source workflow test — 2026-10-10

## Sources and method

Three public YouTube videos were sampled into short local MP4s under `/tmp/` and processed with the CLI, the cached `base.en` Whisper model, and MediaPipe face detection. No source footage is committed to the repository.

| Source | Tested section | Visual content |
| --- | --- | --- |
| [The Economist interview with Tucker Carlson](https://www.youtube.com/watch?v=jpnTQzPHewQ) | 1:00–1:35 | Speaker close-ups and a wide two-person interview shot |
| [Candace Owens, “I'm Pregnant! And Even Crazier, Alive!”](https://www.youtube.com/watch?v=zHyILCWzgpM) | 0:20–0:55 | Portrait talking head with captions already embedded in the source |
| [The White House, presidential address by Donald Trump](https://www.youtube.com/watch?v=iIlqG0untYM) | 16:20–16:55 | Podium speech with a full-width source banner |

The White House video begins with a waiting screen. Its English captions put the first spoken words at 15:57, so the speech test uses a later section.

## Results and fixes

- **Tucker:** The final workflow transcribed 72 words and found 26 single-face and 10 empty samples. It kept the two-person shot wide from 21–31 seconds; an extracted frame at 25 seconds shows both participants.
- **Candace:** The workflow transcribed 123 words and found one face in all 36 sampled frames. Burning a new subtitle layer caused duplicate captions because captions were already in the source. Running with `--no-transcribe` preserved the source captions. The processor now recognizes an existing 9:16 input and skips face analysis and a second vertical encode.
- **Trump:** The short-range face model found no face in 37 samples, yielding a wide shot with a small speaker. The official MediaPipe full-range BlazeFace model found the podium face in all 37 samples. The processor now tries that model when short-range detection is empty and ignores full-range faces smaller than 10% of frame height. A repeat analysis of the earlier ABC debate sample still has its single, dual, and wide scene transitions.

The first fallback pass cropped the Tucker wide interview to one person. At 25 seconds, the full-range model found a face centered at x=959 of 1280 (about 50% off center) while short-range found none. The fallback now accepts only faces within 35% of the horizontal center. The podium face at x=612 is accepted, and the distant side face in the interview is rejected.

The presidential source also has a full-width banner near the bottom. A tight portrait crop keeps the speaker readable but cuts banner text into fragments. For this source, an input copy with the bottom 120 pixels cropped removes the banner before reframing:

```sh
ffmpeg -i /tmp/ytcp_trump_speech.mp4 -vf crop=iw:ih-120:0:0 -c:v libx264 -crf 23 -c:a copy /tmp/ytcp_trump_speech_no_banner.mp4
venv/bin/yt-clip-processor /tmp/ytcp_trump_speech_no_banner.mp4 --clip-length 35 --no-llm-titles
```

## Verification and limits

- Visual contact sheets were checked for the corrected Candace and speech outputs. The final Tucker frame at 25 seconds and the cropped speech output were checked after rendering.
- `PYTHONPATH=src venv/bin/python -m unittest discover -s tests -q`: 22 tests passed.
- Face counts mean detector results from sampled frames, not a manual count of every visible person.
- `--no-transcribe` is the deliberate way to keep captions already burned into a source; there is no reliable automatic caption detection yet.
- Cropping the bottom of the speech source is a source-specific preprocessing step. A general layout that preserves both a full-width ticker and a close face crop remains open.
