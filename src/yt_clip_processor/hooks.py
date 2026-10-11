"""Hooks for candidate clips."""

from bisect import bisect_left, bisect_right

from .hook_signals import _hook_score_chunk, _is_ad_window, _score_clip_body, _score_ending, _score_payoff, _score_standalone_opening


def _find_sentence_boundary(words: list, hook_word_idx: int,
                             max_lookback_sec: float = 8.0,
                             pause_threshold: float = 0.4) -> int:
    """
    Walk backwards from `hook_word_idx` to find the start of the sentence
    or thought that contains the hook phrase.

    A boundary is detected when:
      - The gap between word[n-1].end and word[n].start exceeds pause_threshold
        (speaker paused — natural sentence break in speech)
      - word[n-1] ends with sentence-ending punctuation: . ? !
      - We've walked back more than max_lookback_sec from the hook word

    Returns the index of the first word of the containing sentence.
    Falls back to hook_word_idx if no boundary is found within the lookback window.
    """
    if hook_word_idx <= 0:
        return 0

    hook_time = words[hook_word_idx]["start"]
    cutoff    = hook_time - max_lookback_sec

    for idx in range(hook_word_idx, 0, -1):
        prev_word = words[idx - 1]
        curr_word = words[idx]

        # Hard stop: don't look back further than max_lookback_sec
        if curr_word["start"] < cutoff:
            return idx

        # Pause boundary: gap between end of previous word and start of this one
        gap = curr_word["start"] - prev_word["end"]
        if gap >= pause_threshold:
            return idx

        # Punctuation boundary: previous word ends a sentence
        prev_text = prev_word["word"].strip()
        if prev_text and prev_text[-1] in ".?!":
            return idx

    return 0


def _words_in_range(words: list, start_sec: float, end_sec: float,
                    start_times: list = None) -> list:
    """Return transcript words whose start time falls inside a time range."""
    if start_times is None:
        start_times = [w["start"] for w in words]
    return words[bisect_left(start_times, start_sec):bisect_left(start_times, end_sec)]


def _find_clean_clip_end(words: list, start_sec: float, target_length: float,
                         min_fraction: float = 0.72,
                         extension_sec: float = 8.0,
                         pause_threshold: float = 0.45,
                         end_index: list = None) -> float:
    """
    Pick a natural ending near the requested duration.
    Searches from 72% of target length through target+8 seconds and prefers
    sentence punctuation or a meaningful pause.
    """
    earliest = start_sec + target_length * min_fraction
    target = start_sec + target_length
    latest = target + extension_sec
    if end_index is None:
        end_index = sorted((word["end"], index) for index, word in enumerate(words))
    nearby = [index for _, index in end_index[
        bisect_left(end_index, (earliest, -1)):bisect_right(end_index, (latest, len(words)))
    ]]
    if not nearby:
        return min(target, words[-1]["end"])

    candidates = []
    for idx in nearby:
        if idx == len(words) - 1:
            continue
        word = words[idx]
        next_word = words[idx + 1]
        gap = next_word["start"] - word["end"]
        token = word["word"].strip()
        punctuation = bool(token and token[-1] in ".?!")
        pause = gap >= pause_threshold
        if punctuation or pause:
            distance = abs(word["end"] - target)
            quality_bonus = 2.0 if punctuation else 0.8
            candidates.append((distance - quality_bonus, word["end"]))

    if candidates:
        candidates.sort(key=lambda item: item[0])
        return min(candidates[0][1], words[-1]["end"])
    return min(target, words[-1]["end"])


def _candidate_tokens(candidate: dict) -> set:
    """Normalized token set used to suppress semantically repetitive candidates."""
    import re as _re
    text = candidate.get("clip_text", "").lower()
    stop = {
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on",
        "for", "is", "are", "was", "were", "it", "that", "this", "with",
        "you", "i", "we", "they", "he", "she", "as", "at", "be", "have",
        "has", "had", "do", "does", "did", "so", "not",
    }
    return {t for t in _re.findall(r"[a-z0-9']+", text) if len(t) > 2 and t not in stop}


def _text_similarity(a: dict, b: dict) -> float:
    """Fast Jaccard similarity; dependency-free duplicate-topic suppression."""
    ta = a.get("token_set") or _candidate_tokens(a)
    tb = b.get("token_set") or _candidate_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_hook_clips(words: list, n_hooks: int, clip_length: int,
                    window_words: int = 30, step_words: int = 8,
                    max_lookback_sec: float = 8.0,
                    body_scan_sec: float = 60.0,
                    face_timestamps: set = None,
                    similarity_limit: float = 0.58) -> list:
    """
    Two-stage, dependency-free hook ranker.

    Stage 1 generates many candidates using the original high-interest signal
    detector. Stage 2 reranks each complete clip using:

        opening hook       35%
        sustained body     15%
        payoff             25%
        standalone clarity 15%
        clean ending       10%

    It also chooses a natural ending near the requested duration and suppresses
    both time-overlapping and topic-duplicate clips.
    """
    if not words or n_hooks <= 0:
        return []

    total_duration = words[-1]["end"]
    total_words = len(words)
    total_dur = words[-1]["end"] - words[0]["start"]
    avg_wps = total_words / total_dur if total_dur > 0 else 3.0
    start_times = [word["start"] for word in words]
    end_index = sorted((word["end"], index) for index, word in enumerate(words))
    face_times = sorted(face_timestamps) if face_timestamps is not None else None

    candidates = []
    i = 0
    while i < total_words:
        chunk = words[i:i + window_words]
        if not chunk:
            break
        if chunk[0]["start"] > total_duration - clip_length * 0.5:
            break

        text = " ".join(w["word"] for w in chunk)

        if face_times is not None:
            window_start = chunk[0]["start"]
            window_end = window_start + 15.0
            face_index = bisect_left(face_times, window_start - 1.0)
            has_face = face_index < len(face_times) and face_times[face_index] <= window_end
            if not has_face:
                i += step_words
                continue

        result = _hook_score_chunk(chunk, text, avg_wps)
        if result["score"] <= 0:
            i += step_words
            continue

        trigger_word_idx = i
        for _, hits in result["signals"].items():
            if not hits or not isinstance(hits[0], str):
                continue
            phrase = hits[0].lower()
            if "w/s" in phrase or "number" in phrase:
                continue
            phrase_pos = text.lower().find(phrase)
            if phrase_pos >= 0:
                words_before = len(text.lower()[:phrase_pos].split())
                trigger_word_idx = min(i + words_before, i + len(chunk) - 1)
                break

        boundary_idx = _find_sentence_boundary(
            words, trigger_word_idx, max_lookback_sec=max_lookback_sec)
        actual_start = words[boundary_idx]["start"]

        if _is_ad_window(words, actual_start, clip_length + 8.0, start_times):
            i += step_words
            continue

        actual_end = _find_clean_clip_end(words, actual_start, clip_length, end_index=end_index)
        clip_words = _words_in_range(words, actual_start, actual_end + 0.01, start_times)
        if len(clip_words) < max(20, int(avg_wps * clip_length * 0.35)):
            i += step_words
            continue

        body = _score_clip_body(
            words, actual_start, min(body_scan_sec, actual_end - actual_start), avg_wps,
            start_times)
        standalone = _score_standalone_opening(clip_words)
        payoff = _score_payoff(clip_words, avg_wps)
        ending = _score_ending(clip_words, actual_end, words, start_times)

        hook_score = result["score"]
        body_score = body["body_score"]
        final_score = round(
            hook_score * 0.35
            + body_score * 0.15
            + payoff["score"] * 0.25
            + standalone["score"] * 0.15
            + ending["score"] * 0.10
        )
        final_score = max(0, min(100, final_score))

        preview_words = words[boundary_idx:boundary_idx + 18]
        preview = " ".join(w["word"] for w in preview_words)
        if len(clip_words) > len(preview_words):
            preview += "…"

        clip_text = " ".join(w["word"] for w in clip_words)
        candidate = {
            "start_sec": round(actual_start, 2),
            "end_sec": round(min(actual_end, total_duration), 2),
            "duration_sec": round(min(actual_end, total_duration) - actual_start, 2),
            "timestamp": _seconds_to_hhmmss(actual_start),
            "hook_phrase_sec": round(words[trigger_word_idx]["start"], 2),
            "score": final_score,
            "hook_score": hook_score,
            "body_score": body_score,
            "payoff_score": payoff["score"],
            "standalone_score": standalone["score"],
            "ending_score": ending["score"],
            "signals": result["signals"],
            "body_signals": body["body_signals"],
            "payoff_signals": payoff["signals"],
            "standalone_reasons": standalone["reasons"],
            "ending_reasons": ending["reasons"],
            "hook_preview": preview,
            "clip_text": clip_text,
        }
        candidate["token_set"] = _candidate_tokens(candidate)
        candidates.append(candidate)
        i += step_words

    # Keep a broader shortlist before final diversity selection. This preserves
    # high-quality alternatives when the top candidates overlap or repeat topics.
    candidates.sort(
        key=lambda x: (x["score"], x["payoff_score"], x["standalone_score"]),
        reverse=True,
    )
    shortlist = candidates[:max(n_hooks * 10, 40)]

    kept = []
    for candidate in shortlist:
        overlaps = any(
            existing["start_sec"] < candidate["end_sec"]
            and candidate["start_sec"] < existing["end_sec"]
            for existing in kept
        )
        if overlaps:
            continue

        too_similar = any(
            _text_similarity(candidate, existing) >= similarity_limit
            for existing in kept
        )
        if too_similar:
            continue

        candidate.pop("clip_text", None)
        kept.append(candidate)
        if len(kept) >= n_hooks:
            break

    for candidate in kept:
        candidate.pop("token_set", None)
    return kept


def _seconds_to_hhmmss(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sc = int(s % 60)
    return f"{h:02d}:{m:02d}:{sc:02d}"


def _print_hook_summary(hooks: list):
    """Print a ranked summary table of detected hooks."""
    _ICONS = {
        "named_entity": "🎯", "conflict":  "⚔️",  "revelation": "💥",
        "stakes":       "⚠️",  "assertion": "📢",  "emotion":    "🔥",
        "number":       "🔢",  "question":  "❓",  "pace_spike": "🏃",
    }
    print(f"\n{'═'*62}")
    print(f"  🪝  Hook Analysis — {len(hooks)} candidate(s) found")
    print(f"{'═'*62}")
    for i, h in enumerate(hooks, 1):
        bar        = "█" * round(h["score"] / 5) + "░" * (20 - round(h["score"] / 5))
        hook_score = h.get("hook_score", h["score"])
        body_score = h.get("body_score", 0)
        icons      = " ".join(_ICONS.get(k, k) for k in h["signals"])
        body_icons = " ".join(_ICONS.get(k, k) for k in h.get("body_signals", {})
                              if k not in h["signals"])
        print(f"  #{i}  [{bar}] {h['score']:>3}/100  @  {h['timestamp']}")
        print(f"       \"{h['hook_preview']}\"")
        payoff     = h.get("payoff_score", 0)
        standalone = h.get("standalone_score", 0)
        ending     = h.get("ending_score", 0)
        duration   = h.get("duration_sec", h.get("end_sec", 0) - h.get("start_sec", 0))
        print(f"       Hook {hook_score:>3}  Body {body_score:>3}  Payoff {payoff:>3}  "
              f"Standalone {standalone:>3}  Ending {ending:>3}")
        print(f"       Duration: {duration:.1f}s")
        print(f"       Open : {icons if icons else '(none)'}")
        if body_icons:
            print(f"       Body : {body_icons}")
        print()
    print(f"{'═'*62}\n")
