"""Subtitles stage of the video processor."""

from pathlib import Path
from .media import _run_ffmpeg


def _write_karaoke_ass(words_json_path: Path, ass_path: Path, font: str = "Arial",
                       scenes: list = None):
    """
    Write an ASS subtitle file with Opus-Clip-style karaoke highlighting.

    Layout
    ------
    • Each "chunk" of N words is shown as a single line for its full duration.
    • The currently-spoken word is yellow; all other words in the chunk are white.
    • This is achieved by emitting one Dialogue event *per word* in the chunk,
      each covering only that word's time window, with the full chunk text where
      only that word carries the yellow colour tag.  The events are stacked on
      the same layer so they replace each other seamlessly.

    Style
    -----
    • Font: bold, 88 px
    • Colour: white (#FFFFFF) base, yellow (#00FFFF in BGR = &H00FFFF& in ASS)
    • Outline: 4 px solid black — no shadow box
    • Position: bottom-center (alignment 2) with a 180 px bottom margin
    • Split-screen scenes use alignment 5 (middle-center, no margin)
    """
    import json as _json

    font_name = Path(font).stem if Path(font).suffix.lower() == ".ttf" else font

    with open(words_json_path, "r", encoding="utf-8") as jf:
        data = _json.load(jf)

    all_words       = data["words"]
    words_per_chunk = data.get("words_per_chunk", 5)
    delay           = data.get("delay", 0.0)

    # ── Scene lookup ──
    scene_ranges = scenes or []

    def _style_for_time(t: float) -> str:
        for s in scene_ranges:
            s0 = s.get("start_sec", s.get("start", 0))
            s1 = s.get("end_sec",   s.get("end", float("inf")))
            if s0 <= t < s1:
                return "Split" if s.get("mode") in ("dual", "reaction") else "Default"
        return "Default"

    # ── Timestamp helpers ──
    def _sec_to_ass(sec: float) -> str:
        centiseconds = round(max(0.0, sec) * 100)
        h, remainder = divmod(centiseconds, 360_000)
        m, remainder = divmod(remainder, 6_000)
        s, cs = divmod(remainder, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # ── ASS colour constants (BGR order, &HAABBGGRR&, AA=00 = opaque) ──
    WHITE  = "&H00FFFFFF&"
    YELLOW = "&H0000FFFF&"   # pure yellow in BGR = 00,FF,FF → &H0000FFFF&

    # ── Header ──
    style_fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    # BorderStyle 1 = outline+shadow (we set Shadow=0 → outline only)
    # MarginL/R = 60px each side to prevent text clipping on narrow displays/reposts
    # MarginV (Default) = 420px ≈ 1/4 up from bottom, clear of TikTok caption bar
    def _style_line(name, alignment, margin_v):
        return (
            f"Style: {name},{font_name},52,{WHITE},{WHITE},&H00000000&,&H00000000&,"
            f"-1,0,0,0,100,100,0,0,1,4,0,{alignment},40,40,{margin_v},1\n"
        )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 720\n"
        "PlayResY: 1280\n"
        "\n"
        "[V4+ Styles]\n"
        f"{style_fmt}"
        + _style_line("Default", 2, 280)   # ~1/4 up from bottom, above TikTok caption
        + _style_line("Split",   5, 0)     # middle-center (split-screen)
        + "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    # ── Build chunks ──
    dialogue_lines = []

    i = 0
    while i < len(all_words):
        chunk = all_words[i : i + words_per_chunk]
        if not chunk:
            break

        chunk_start = max(0.0, chunk[0]["start"] + delay)
        chunk_end   = max(chunk_start + 0.05, chunk[-1]["end"] + delay)

        # Extend to next chunk's start (no blank gap between chunks)
        if i + words_per_chunk < len(all_words):
            next_start  = all_words[i + words_per_chunk]["start"] + delay
            chunk_end   = max(chunk_end, next_start)

        style = _style_for_time(chunk_start)

        # Upper-case display words
        display = [w["word"].upper() for w in chunk]

        # Emit one Dialogue event per word in the chunk.
        # Each event spans only that word's active time window.
        for j, word_data in enumerate(chunk):
            w_start = max(0.0, word_data["start"] + delay)
            # Word is "active" until the next word begins (or chunk ends)
            if j + 1 < len(chunk):
                w_end = max(w_start + 0.04, chunk[j + 1]["start"] + delay)
            else:
                w_end = chunk_end

            # Build the full line: words before active = white (default),
            # active word = yellow, words after = white (slightly dimmed via alpha)
            parts = []
            for k, dw in enumerate(display):
                if k < j:
                    # Already spoken — white but slightly transparent (70%)
                    parts.append(f"{{\\c{WHITE}\\alpha&H46&}}{dw}{{\\alpha&H00&}}")
                elif k == j:
                    # Currently spoken — yellow, fully opaque
                    parts.append(f"{{\\c{YELLOW}}}{dw}{{\\c{WHITE}}}")
                else:
                    # Not yet spoken — white, full opacity
                    parts.append(dw)

            text = " ".join(parts)
            dialogue_lines.append(
                f"Dialogue: 0,{_sec_to_ass(w_start)},{_sec_to_ass(w_end)},"
                f"{style},,0,0,0,,{text}"
            )

        i += words_per_chunk

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(dialogue_lines))
        f.write("\n")


def _resolve_font(font_arg: str = None) -> str:
    """
    Return a font name/path to embed in the ASS style.
    Priority:
      1. --font CLI arg (if given and file exists)
      2. A Bebas Neue .ttf found anywhere on PATH-like locations
      3. A safe system fallback ("Arial" on Windows/Mac, "DejaVu Sans" on Linux)
    Returns just the font *name* (not path) because ASS uses names, not paths.
    The font must be installed / registered with the OS for ffmpeg libass to find it.
    If the user passes a raw .ttf path we copy it into the working dir and register
    its basename so libass can pick it up via the -fontsdir trick in burn_subtitles.
    """
    import platform

    if font_arg:
        p = Path(font_arg)
        if p.exists():
            return str(p)           # full path returned; burn_subtitles handles it
        # Treat as a font name (e.g. "Arial")
        return font_arg

    # System fallbacks
    system = platform.system()
    if system == "Windows":
        return "Arial"
    elif system == "Darwin":
        return "Helvetica Neue"
    else:
        return "DejaVu Sans"


def _ts_to_seconds(ts: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    ts = ts.replace(",", ".")
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + float(f"0.{ms}")


def _srt_to_ass(srt_path: Path, ass_path: Path, font: str = "Arial",
                scenes: list = None):
    """
    Convert SRT to ASS format with scene-aware subtitle positioning.

    Two styles are always written:
      - Default : bottom-center (alignment 2)  — used during single-face scenes
      - Split   : middle-center (alignment 5)  — used during split-screen scenes

    Each dialogue line is tagged with the correct style by looking up which
    scene covers its start timestamp.  If no scenes list is provided, all
    subtitles use the Default (bottom) style.

    `font` may be a font name or an absolute path to a .ttf file.
    """
    font_name = Path(font).stem if Path(font).suffix.lower() == ".ttf" else font

    # Build a sorted list of (start_sec, end_sec, mode) from scenes
    scene_ranges = []
    if scenes:
        for s in scenes:
            # scenes store frame numbers; convert to seconds via fps embedded in
            # the scene dict if available, otherwise we rely on caller to pass
            # pre-converted seconds.  render_split_screen stores fps separately,
            # so we accept both frames (int) and seconds (float) gracefully.
            scene_ranges.append(s)   # stored as-is; lookup below handles both

    def _style_for_time(start_sec: float) -> str:
        """Return 'Split' if this timestamp falls in a dual/split scene, else 'Default'."""
        if not scene_ranges:
            return "Default"
        for s in scene_ranges:
            # Scenes may store seconds directly or as frame-based values with an fps key
            s_start = s.get("start_sec", s.get("start", 0))
            s_end   = s.get("end_sec",   s.get("end",   float("inf")))
            if s_start <= start_sec < s_end:
                return "Split" if s.get("mode") in ("dual", "reaction") else "Default"
        return "Default"

    style_line = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 720\n"
        "PlayResY: 1280\n"
        "\n"
        "[V4+ Styles]\n"
        f"{style_line}"
        # Default style — bottom third (alignment 2), 427px margin from bottom (~1/3 up on 1280px)
        f"Style: Default,{font_name},35,&H00FFFFFF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,1,2,0,0,427,1\n"
        # Split style — middle-center (alignment 5), no margin
        f"Style: Split,{font_name},35,&H00FFFFFF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,1,5,0,0,0,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def srt_ts_to_ass(ts):
        ts = ts.replace(",", ".")
        h, m, rest = ts.split(":")
        s, ms = rest.split(".")
        return f"{int(h)}:{m}:{s}.{ms[:2]}"

    with open(srt_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    dialogue = []
    for block in raw.split("\n\n"):
        parts = block.strip().split("\n")
        if len(parts) < 3:
            continue
        times = parts[1].split(" --> ")
        if len(times) != 2:
            continue
        start_raw = times[0].strip()
        end_raw   = times[1].strip()
        start_sec = _ts_to_seconds(start_raw)
        style     = _style_for_time(start_sec)
        start_ts  = srt_ts_to_ass(start_raw)
        end_ts    = srt_ts_to_ass(end_raw)
        text      = " ".join(parts[2:]).replace("\n", "\\N")
        dialogue.append(f"Dialogue: 0,{start_ts},{end_ts},{style},,0,0,0,,{text}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(dialogue))


def burn_subtitles(video_path: Path, srt_path: Path, output_dir: Path,
                   font: str = "Arial", scenes: list = None,
                   output_path: Path = None, start: float = None,
                   duration: float = None) -> Path:
    """
    Burn subtitles using ASS format with scene-aware positioning.
    Subtitles automatically switch between bottom-center (single-face scenes)
    and middle-center (split-screen scenes) based on the scenes list.
    - font   -> font name or path to .ttf file
    - scenes -> list of scene dicts from analyse_faces() with 'start_sec'/'end_sec'/'mode'
    - start/duration -> optional source interval for a final clip; subtitle times are relative
    """
    import re

    safe_out = output_path or output_dir / "final_subtitled.mp4"

    if safe_out.exists():
        print(f"\u23e9  Subtitled video already exists \u279c {safe_out.name}")
        return safe_out

    has_split = scenes and any(s.get("mode") in ("dual", "reaction") for s in scenes)

    # Prefer karaoke ASS if per-word JSON is available (written by transcribe_video)
    words_json_path = srt_path.with_suffix(".words.json")
    ass_path = output_dir / "subs_temp.ass"

    if words_json_path.exists():
        mode_label = "karaoke" + (" + scene-aware" if has_split else "")
        print(f"\n\U0001f3ac  Burning subtitles ({mode_label}) \u2026")
        _write_karaoke_ass(words_json_path, ass_path, font=font, scenes=scenes)
    else:
        print(f"\n\U0001f3ac  Burning subtitles ({'scene-aware' if has_split else 'bottom-center'}) \u2026")
        _srt_to_ass(srt_path, ass_path, font=font, scenes=scenes)

    # Escape the ASS path for ffmpeg's -vf filter string.
    # On Windows/WSL, drive letters need special escaping: C:/ -> C\:/
    # re.sub backreference fix: use r"\1" (not r"\\1") so group 1 is inserted correctly.
    ass_str = str(ass_path).replace("\\", "/")
    ass_str = re.sub(r"^([A-Za-z]):/", r"\1\\:/", ass_str)

    # If the font is a .ttf path, tell libass where to find it via fontsdir
    vf_parts = []
    font_path = Path(font)
    if font_path.suffix.lower() == ".ttf" and font_path.exists():
        fonts_dir = str(font_path.parent).replace("\\", "/")
        fonts_dir = re.sub(r"^([A-Za-z]):/", r"\1\\:/", fonts_dir)
        vf_parts.append(f"ass='{ass_str}':fontsdir='{fonts_dir}'")
    else:
        vf_parts.append(f"ass='{ass_str}'")

    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd.extend(["-ss", str(start)])
    cmd.extend(["-i", str(video_path)])
    if duration is not None:
        cmd.extend(["-t", str(duration)])
    cmd.extend([
        "-vf", ",".join(vf_parts),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        str(safe_out),
    ])

    _run_ffmpeg(cmd)
    ass_path.unlink(missing_ok=True)
    print(f"\u2705  Subtitled video \u279c {safe_out.name}")
    return safe_out
