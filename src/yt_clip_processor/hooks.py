"""Select complete spoken clips without topic or keyword gates."""

import re
from bisect import bisect_left


_CONTEXT_OPENERS = {"and", "but", "so", "because", "then", "also", "anyway"}
_VAGUE_OPENERS = {"he", "she", "they", "it", "this", "that", "these", "those"}
_UNFINISHED_WORDS = {"and", "but", "because", "if", "when", "the", "a", "to", "of"}
_AD_PHRASES = ("sponsored by", "sponsor of today's", "use my code", "promo code",
               "link in the description", "thanks to our sponsor")
_STOP_WORDS = {"the", "and", "for", "that", "this", "with", "from", "you", "are",
               "was", "were", "have", "has", "had", "they", "their", "about"}


def _words_in_range(words, start_sec, end_sec, start_times=None):
    if start_times is None:
        start_times = [word["start"] for word in words]
    return words[bisect_left(start_times, start_sec):bisect_left(start_times, end_sec)]


def _sentence_end(word):
    return word["word"].strip().endswith((".", "?", "!"))


def _boundaries(words):
    """Return start indexes and possible clip endings at speech boundaries."""
    starts = [0]
    endings = []
    for index, word in enumerate(words):
        gap = words[index + 1]["start"] - word["end"] if index + 1 < len(words) else 0
        punctuation = _sentence_end(word)
        if punctuation or gap >= 0.55 or index == len(words) - 1:
            endings.append((index, word["end"], punctuation, gap))
            if index + 1 < len(words):
                starts.append(index + 1)
    return starts, endings


def _tokens(words):
    return [re.sub(r"[^\w']", "", word["word"].lower()) for word in words]


def _score_clip(clip_words, duration, avg_wps, end_punctuation, end_gap):
    tokens = _tokens(clip_words)
    first = tokens[0] if tokens else ""
    text = " ".join(word["word"] for word in clip_words).lower()
    reasons = []

    opening = 70
    if first in _CONTEXT_OPENERS:
        opening -= 30
        reasons.append("opening depends on previous sentence")
    elif first in _VAGUE_OPENERS:
        opening -= 18
        reasons.append("opening has an unclear reference")
    else:
        reasons.append("opens at a complete thought")
    if any("?" in word["word"] for word in clip_words[:18]):
        opening += 10
        reasons.append("early question")

    density = len(clip_words) / max(duration, 1)
    relative_density = density / max(avg_wps, 0.1)
    long_pauses = sum(clip_words[i + 1]["start"] - word["end"] > 3
                      for i, word in enumerate(clip_words[:-1]))
    lexical_variety = len(set(tokens)) / max(len(tokens), 1)
    body = 55
    if 0.65 <= relative_density <= 1.55:
        body += 20
        reasons.append("sustained speech")
    elif relative_density < 0.5:
        body -= 25
    if lexical_variety >= 0.3:
        body += 10
    body -= min(40, long_pauses * 20)

    first_third = clip_words[:max(1, len(clip_words) // 3)]
    latter = clip_words[len(clip_words) // 2:]
    question_then_response = (any("?" in word["word"] for word in first_third)
                              and len(latter) >= 20)
    sentence_count = sum(_sentence_end(word) for word in clip_words)
    arc = 45 + min(25, sentence_count * 5)
    if question_then_response:
        arc += 25
        reasons.append("question followed by a developed response")
    elif sentence_count >= 3:
        reasons.append("multiple complete statements")

    ending = 35
    if end_punctuation:
        ending += 40
        reasons.append("ends on a sentence boundary")
    if end_gap >= 0.55:
        ending += 20
        reasons.append("ends before a pause")
    if tokens[-1] in _UNFINISHED_WORDS:
        ending -= 40

    parts = {"opening": max(0, min(100, opening)),
             "body": max(0, min(100, body)),
             "arc": max(0, min(100, arc)),
             "ending": max(0, min(100, ending))}
    score = round(parts["opening"] * 0.30 + parts["body"] * 0.20
                  + parts["arc"] * 0.25 + parts["ending"] * 0.25)
    if any(phrase in text for phrase in _AD_PHRASES):
        return 0, parts, ["contains a sponsor or promotion"]
    return score, parts, reasons


def _candidate_tokens(candidate):
    return {token for token in _tokens(candidate["words"])
            if len(token) > 2 and token not in _STOP_WORDS}


def _similarity(left, right):
    a, b = left["tokens"], right["tokens"]
    return len(a & b) / len(a | b) if a and b else 0


def find_hook_clips(words, n_hooks, clip_length, face_timestamps=None,
                    min_score=65, similarity_limit=0.6, semantic_scorer=None):
    """Rank transcript windows across the video and keep distinct strong clips.

    `face_timestamps` is accepted for older callers but never filters speech;
    scene and face handling happens during rendering.
    """
    if not words or n_hooks <= 0:
        return []
    starts, endings = _boundaries(words)
    end_times = [end[1] for end in endings]
    total_duration = words[-1]["end"] - words[0]["start"]
    avg_wps = len(words) / max(total_duration, 1)
    candidates = []
    for start_index in starts:
        start = words[start_index]["start"]
        earliest = start + clip_length * 0.72
        latest = start + clip_length * 1.18
        left = bisect_left(end_times, earliest)
        right = bisect_left(end_times, latest)
        possible = [end for end in endings[left:right] if end[0] >= start_index + 19]
        if not possible:
            continue
        end_index, end, punctuation, gap = min(
            possible,
            key=lambda option: (abs(option[1] - (start + clip_length))
                                - (2 if option[2] else 0) - min(option[3], 1)),
        )
        clip_words = words[start_index:end_index + 1]
        duration = end - start
        if len(clip_words) < max(20, int(duration * 0.75)):
            continue
        score, parts, reasons = _score_clip(clip_words, duration, avg_wps,
                                             punctuation, gap)
        if score < (40 if semantic_scorer else min_score):
            continue
        preview = " ".join(word["word"] for word in clip_words[:20])
        candidate = {
            "start_sec": round(start, 2), "end_sec": round(end, 2),
            "duration_sec": round(duration, 2), "timestamp": _timestamp(start),
            "score": score, "score_parts": parts, "reasons": reasons,
            "hook_preview": preview + ("…" if len(clip_words) > 20 else ""),
            "clip_text": " ".join(word["word"] for word in clip_words),
            "context_before": " ".join(word["word"] for word in
                                          words[max(0, start_index - 25):start_index]),
            "context_after": " ".join(word["word"] for word in
                                         words[end_index + 1:end_index + 26]),
            "words": clip_words,
        }
        candidate["tokens"] = _candidate_tokens(candidate)
        candidates.append(candidate)

    candidates.sort(key=lambda item: (item["score"], item["score_parts"]["opening"],
                                      -abs(item["duration_sec"] - clip_length)), reverse=True)
    if semantic_scorer:
        limit = min(48, max(32, n_hooks * 10))
        shortlist = []
        per_section = {}
        for candidate in candidates:
            section = int(candidate["start_sec"] // clip_length)
            if per_section.get(section, 0) >= 3:
                continue
            shortlist.append(candidate)
            per_section[section] = per_section.get(section, 0) + 1
            if len(shortlist) == limit:
                break
        candidates = shortlist
        for index, (semantic_score, reason) in semantic_scorer(candidates).items():
            if 0 <= index < len(candidates) and 0 <= semantic_score <= 100:
                candidate = candidates[index]
                candidate["structural_score"] = candidate["score"]
                candidate["semantic_score"] = semantic_score
                candidate["score"] = round(0.35 * candidate["score"] + 0.65 * semantic_score)
                candidate["reasons"].append(f"semantic assessment: {reason}")
        candidates = [candidate for candidate in candidates if candidate["score"] >= min_score]
        candidates.sort(key=lambda item: (item["score"], item["score_parts"]["opening"]),
                        reverse=True)
    selected = []
    for candidate in candidates:
        if any(existing["start_sec"] < candidate["end_sec"]
               and candidate["start_sec"] < existing["end_sec"]
               for existing in selected):
            continue
        if any(_similarity(candidate, existing) >= similarity_limit for existing in selected):
            continue
        selected.append(candidate)
        if len(selected) == n_hooks:
            break
    for candidate in selected:
        candidate.pop("words")
        candidate.pop("tokens")
    return selected


def _timestamp(seconds):
    whole = int(max(0, seconds))
    return f"{whole // 3600:02d}:{(whole // 60) % 60:02d}:{whole % 60:02d}"


def _print_hook_summary(hooks):
    print(f"\nAutomatic clip selection: {len(hooks)} clip(s) passed")
    for index, hook in enumerate(hooks, 1):
        print(f"  #{index} {hook['timestamp']}–{_timestamp(hook['end_sec'])} "
              f"({hook['score']}/100): {hook['hook_preview']}")
        print(f"     {', '.join(hook['reasons'])}")
