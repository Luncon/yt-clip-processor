"""Hook signals for candidate clips."""

from bisect import bisect_left



_HOOK_NAMED_ENTITIES = [
    "biden", "trump", "obama", "harris", "pelosi", "schumer", "mcconnell",
    "desantis", "gavin newsom", "newsom", "aoc", "ocasio-cortez",
    "bernie", "sanders", "hillary", "clinton", "pence",
    "zelensky", "putin", "xi jinping", "macron", "trudeau",
    "the white house", "the fbi", "the cia", "the doj",
    "the fed", "the supreme court", "the pentagon", "nato",
    "mainstream media", "msm", "cnn", "msnbc", "fox news",
    "the new york times", "washington post", "the establishment",
    "the deep state", "big pharma", "wall street", "silicon valley",
    "the left", "the right", "the democrats", "the republicans",
    "the globalists", "the elites", "the regime",
    "erika kirk", "charlie kirk", "kirk",
    "epstein", "jeffrey epstein", "epstein island",
    "israel", "israeli", "hamas", "gaza", "netanyahu",
    "egypt", "egyptian",
    "the cartel", "cartels", "ms-13", "drug cartel",
]


_HOOK_CONFLICT = [
    "slammed", "blasted", "destroyed", "crushed", "attacked", "ripped",
    "fired back", "clapped back", "called out", "exposed", "dismantled",
    "torched", "eviscerated", "humiliated", "embarrassed", "obliterated",
    "shut down", "taken apart", "taken down",
    "goes after", "went after", "comes for", "came for",
    "confronted", "challenged", "accused", "blamed",
    "lied", "lied to", "caught lying", "caught on camera",
    "fact checked", "debunked", "proven wrong",
]


_HOOK_REVELATION = [
    "just came out", "breaking", "just broke", "developing",
    "just admitted", "just confessed", "just announced", "just revealed",
    "admitted", "confessed", "revealed", "leaked", "obtained",
    "exclusive", "confirmed", "sources say", "according to sources",
    "we just learned", "it turns out",
    "the truth is", "the real story", "what really happened",
    "what they're not telling you", "what the media won't show",
    "they don't want you to see", "they don't want you to know",
    "suppressed", "censored", "banned", "deleted",
    "cover up", "cover-up", "covering up", "hiding",
]


_HOOK_STAKES = [
    "threatens", "could end", "end of",
    "unprecedented", "historic", "crisis", "emergency",
    "disaster", "catastrophe", "collapse",
    "ban", "banned", "criminalize", "illegal",
    "arrest", "arrested", "indicted", "charged",
    "impeach", "impeached", "removed", "resign", "resigned",
    "declare war", "invasion", "attack on",
    "your rights", "freedom", "losing our",
    "they want to", "they're trying to", "they plan to",
    "agenda", "they need you to", "wake up",
]


_HOOK_ASSERTION = [
    "here's the thing", "here's what", "here's why",
    "the fact is", "the truth is", "the reality is",
    "let me be clear", "let me be honest", "let me tell you",
    "i'll tell you", "i'll say it", "i'll be direct",
    "nobody is saying", "no one is talking about",
    "what everyone is missing", "what no one will say",
    "this is important", "this matters", "pay attention",
    "think about this", "think about what",
    "the reason", "the real reason", "the actual reason",
    "this is what happens", "this is exactly",
    "you have to understand", "you need to understand",
    "understand this",
]


_HOOK_EMOTION = [
    "outrageous", "outraged", "disgusting", "disgraceful",
    "unacceptable", "shameful", "appalling", "horrifying",
    "terrifying", "dangerous", "radical", "extreme",
    "insane", "absurd", "ridiculous", "unbelievable",
    "corrupt", "corruption", "criminal",
    "evil", "sick", "twisted", "deranged", "delusional",
    "hypocrisy", "hypocrite", "hypocritical",
    "double standard", "rigged", "stolen", "fraud",
    "lie", "lies", "lying", "dishonest",
]


_HOOK_QUESTIONS = [
    "why is", "why are", "why does", "why did", "why would",
    "how is it", "how did", "how can",
    "what is going on", "what happened", "what does this mean",
    "when did", "who decided", "who is responsible",
    "do you think", "do you believe",
]


_HOOK_WEIGHTS = {
    "named_entity":  24,
    "conflict":      22,
    "revelation":    20,
    "stakes":        18,
    "assertion":     14,
    "emotion":       12,
    "number":         8,
    "question":       6,
}


_HOOK_KEYWORD_WEIGHTS = {
    # Extremely strong
    "israel": 11,
    "jeffrey epstein": 18,
    "epstein": 16,
    "caught on camera": 15,
    "murdered": 14,
    "murder": 13,
    "torture": 14,
    "tortured": 14,
    "assassinated": 14,
    "cover-up": 13,
    "coverup": 13,

    # Strong institutions, regions, and high-stakes topics
    "middle east": 12,
    "cia": 12,
    "fbi": 11,
    "doj": 10,
    "department of justice": 10,
    "mossad": 12,
    "hamas": 11,
    "gaza": 11,
    "pentagon": 9,
    "white house": 8,
    "supreme court": 8,
    "congress": 7,
    "nato": 7,

    # Strong revelation / legal / conflict language
    "whistleblower": 11,
    "declassified": 10,
    "leaked": 10,
    "exclusive": 9,
    "breaking": 9,
    "confirmed": 8,
    "indicted": 9,
    "convicted": 9,
    "charged": 7,
    "arrested": 7,
    "raid": 7,
    "genocide": 12,
    "national security": 9,
    "human rights": 7,

    # Medium-strength controversy and ethics language
    "illegal": 7,
    "illegally": 7,
    "unethical": 6,
    "immoral": 5,
    "corruption": 7,
    "fraud": 7,
    "evidence": 6,
    "footage": 5,
    "recording": 5,
    "documents": 4,
    "files": 3,

    # Broader geopolitical terms
    "ukraine": 7,
    "russia": 7,
    "china": 7,
    "war": 5,
    "conflict": 4,
    "sanctions": 5,
    "crisis": 4,
    "emergency": 4,
}


_HOOK_KEYWORD_BONUS_CAP = 45


_HOOK_BOUNDARY_BONUS = 8


_HOOK_PACE_BONUS     = 6


_AD_PHRASES = [
    # direct sponsor callouts
    "this video is sponsored", "this video is brought to you",
    "today's sponsor", "today's video is sponsored",
    "brought to you by", "paid partnership", "paid promotion",
    "in partnership with", "working with", "thanks to our sponsor",
    "thank our sponsor", "special thanks to",
    # promo actions
    "use my code", "use code", "promo code", "discount code",
    "coupon code", "affiliate link", "link in the description",
    "link in bio", "check the description", "check out the link",
    "use the link below", "swipe up",
    # subscription / merch plugs
    "check out their website", "visit their site", "go to",
    "download the app", "sign up for free", "free trial",
    "first month free", "percent off", "% off", "dollars off",
    # creator economy ad reads
    "nordvpn", "expressvpn", "surfshark", "squarespace", "wix",
    "skillshare", "brilliant", "curiositystream", "nebula",
    "manscaped", "dollar shave", "hello fresh", "factor meals",
    "athletic greens", "ag1", "betterhelp", "netsuite",
    "hubspot", "shopify", "raycon", "ridge wallet",
    "established titles", "ground news",
]


def _hook_contains(text: str, phrases: list) -> list:
    t = text.lower()
    return [p for p in phrases if p in t]


def _is_ad_window(words: list, start_sec: float, clip_length: float,
                  start_times: list = None) -> bool:
    """
    Return True if the clip window [start_sec, start_sec+clip_length] contains
    any sponsor/ad phrase.  Checks the full clip, not just the opening window,
    so mid-clip ad reads also disqualify the candidate.
    """
    if start_times is None:
        start_times = [w["start"] for w in words]
    left = bisect_left(start_times, start_sec)
    right = bisect_left(start_times, start_sec + clip_length)
    clip_words = words[left:right]
    text = " ".join(w["word"] for w in clip_words).lower()
    return any(phrase in text for phrase in _AD_PHRASES)


def _hook_weighted_keyword_hits(text: str) -> tuple[list, int]:
    """
    Return unique weighted keyword matches and their capped bonus.

    Longer phrases are checked first so "Jeffrey Epstein" is not also counted
    as a second independent "Epstein" hit from the same wording.
    """
    import re as _re

    lowered = text.lower()
    occupied = []
    matches = []

    for phrase, weight in sorted(
        _HOOK_KEYWORD_WEIGHTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = r"(?<!\w)" + _re.escape(phrase) + r"(?!\w)"
        match = _re.search(pattern, lowered)
        if not match:
            continue

        span = match.span()
        overlaps_existing = any(
            span[0] < end and span[1] > start
            for start, end in occupied
        )
        if overlaps_existing:
            continue

        occupied.append(span)
        matches.append((phrase, weight))

    total = min(
        _HOOK_KEYWORD_BONUS_CAP,
        sum(weight for _, weight in matches),
    )
    return matches, total


def _hook_count_numbers(text: str) -> int:
    import re as _re
    written = {
        "zero","one","two","three","four","five","six","seven","eight",
        "nine","ten","eleven","twelve","thirteen","fourteen","fifteen",
        "sixteen","seventeen","eighteen","nineteen","twenty","hundred",
        "thousand","million","billion","percent",
    }
    digit_count  = len(_re.findall(r"\b\d[\d,\.]*\b", text))
    word_count   = sum(1 for w in _re.findall(r"\b\w+\b", text.lower()) if w in written)
    return digit_count + word_count


def _hook_score_chunk(chunk_words: list, text: str, avg_wps: float) -> dict:
    raw = {}
    signals = {}

    # Named entity — naming a politician/institution is the primary political hook signal
    ne_hits = _hook_contains(text, _HOOK_NAMED_ENTITIES)
    if ne_hits:
        signals["named_entity"] = ne_hits[:2]
        raw["named_entity"] = _HOOK_WEIGHTS["named_entity"]
    else:
        raw["named_entity"] = 0

    # Conflict / attack language
    cf_hits = _hook_contains(text, _HOOK_CONFLICT)
    if cf_hits:
        signals["conflict"] = cf_hits[:2]
        raw["conflict"] = _HOOK_WEIGHTS["conflict"]
    else:
        raw["conflict"] = 0

    # Revelation / breaking framing
    rv_hits = _hook_contains(text, _HOOK_REVELATION)
    if rv_hits:
        signals["revelation"] = rv_hits[:2]
        raw["revelation"] = _HOOK_WEIGHTS["revelation"]
    else:
        raw["revelation"] = 0

    # Stakes / consequence language
    sk_hits = _hook_contains(text, _HOOK_STAKES)
    if sk_hits:
        signals["stakes"] = sk_hits[:2]
        raw["stakes"] = _HOOK_WEIGHTS["stakes"]
    else:
        raw["stakes"] = 0

    # Strong assertion opener
    as_hits = _hook_contains(text, _HOOK_ASSERTION)
    if as_hits:
        signals["assertion"] = as_hits[:2]
        raw["assertion"] = _HOOK_WEIGHTS["assertion"]
    else:
        raw["assertion"] = 0

    # Emotion / outrage language
    em_hits = _hook_contains(text, _HOOK_EMOTION)
    if em_hits:
        signals["emotion"] = em_hits[:2]
        raw["emotion"] = _HOOK_WEIGHTS["emotion"]
    else:
        raw["emotion"] = 0

    # Number / stat (polling numbers, dates, dollar amounts)
    n = _hook_count_numbers(text)
    if n >= 2:
        signals["number"] = [f"{n} numbers/stats"]
        raw["number"] = _HOOK_WEIGHTS["number"]
    elif n == 1:
        signals["number"] = ["1 number/stat"]
        raw["number"] = int(_HOOK_WEIGHTS["number"] * 0.6)
    else:
        raw["number"] = 0

    # Question — weak signal for political content
    q_hits = _hook_contains(text, _HOOK_QUESTIONS)
    if q_hits or "?" in text:
        signals["question"] = q_hits[:1] or ["?"]
        raw["question"] = _HOOK_WEIGHTS["question"]
    else:
        raw["question"] = 0

    # Stacking bonus: multiple categories firing together = much stronger hook
    categories_hit = sum(1 for v in raw.values() if v > 0)
    stack_bonus = 0
    if categories_hit >= 4:
        stack_bonus = 15
    elif categories_hit >= 3:
        stack_bonus = 8
    elif categories_hit >= 2:
        stack_bonus = 3

    # Boundary bonus (first word capitalised → likely sentence start)
    boundary = _HOOK_BOUNDARY_BONUS if chunk_words[0]["word"].strip()[:1].isupper() else 0

    # Pace spike bonus
    duration = chunk_words[-1]["end"] - chunk_words[0]["start"]
    chunk_wps = len(chunk_words) / duration if duration > 0 else 0
    pace_bonus = _HOOK_PACE_BONUS if (avg_wps > 0 and chunk_wps > avg_wps * 1.35) else 0
    if pace_bonus:
        signals["pace_spike"] = [f"{chunk_wps:.1f} w/s vs avg {avg_wps:.1f}"]

    # Individual keyword layer. This supplements category scoring rather than
    # replacing it, so an important proper noun can meaningfully distinguish
    # otherwise similar candidates.
    keyword_hits, keyword_bonus = _hook_weighted_keyword_hits(text)
    if keyword_hits:
        signals["weighted_keywords"] = [
            f"{phrase} (+{weight})"
            for phrase, weight in keyword_hits[:5]
        ]

    score = min(
        100,
        round(
            sum(raw.values())
            + stack_bonus
            + boundary
            + pace_bonus
            + keyword_bonus
        ),
    )
    return {
        "score": score,
        "signals": signals,
        "keyword_bonus": keyword_bonus,
    }


def _score_clip_body(words: list, start_sec: float, scan_sec: float,
                     avg_wps: float, start_times: list = None) -> dict:
    """
    Score the body of a clip for signal density across the first `scan_sec`.
    Slides 30-word windows across that range and averages their hook scores.
    Returns body_score (0-100) and all signal types found.
    """
    if start_times is None:
        start_times = [w["start"] for w in words]
    left = bisect_left(start_times, start_sec)
    right = bisect_left(start_times, start_sec + scan_sec)
    body_words = words[left:right]
    if not body_words:
        return {"body_score": 0, "body_signals": {}, "unique_categories": 0}

    all_signals: dict = {}
    scores = []
    for j in range(0, len(body_words), 10):
        chunk = body_words[j : j + 30]
        if not chunk:
            break
        text   = " ".join(w["word"] for w in chunk)
        result = _hook_score_chunk(chunk, text, avg_wps)
        if result["score"] > 0:
            scores.append(result["score"])
            for k, v in result["signals"].items():
                if k not in all_signals:
                    all_signals[k] = v

    body_score = min(100, round(sum(scores) / len(scores))) if scores else 0
    return {"body_score": body_score, "body_signals": all_signals,
            "unique_categories": len(all_signals)}


_CONTEXT_DEPENDENT_OPENERS = (
    "and ", "but ", "so ", "because ", "then ", "also ",
    "like i said", "as i said", "as i mentioned", "as we discussed",
    "he said", "she said", "they said", "it was", "this was",
    "that was", "they were", "the other thing", "another thing",
)


_VAGUE_OPENING_WORDS = {
    "he", "she", "they", "it", "this", "that", "these", "those",
    "there", "him", "her", "them", "his", "their",
}


_PAYOFF_PHRASES = [
    "it turned out", "turns out", "the result was", "the reason was",
    "the truth was", "what happened next", "and that is when",
    "and that's when", "then i realized", "then we realized",
    "we discovered", "they discovered", "we found out", "i found out",
    "in the end", "eventually", "finally", "which means",
    "that means", "because of that", "as a result", "the answer is",
    "here's the answer", "the conclusion", "the outcome",
    "everyone survived", "no one survived", "was convicted", "was arrested",
    "was fired", "was removed", "won the case", "lost the case",
]


_UNFINISHED_ENDINGS = (
    "and", "but", "because", "so", "then", "or", "if", "when", "while",
    "which", "that", "to", "of", "with", "for", "from", "about",
    "the", "a", "an", "this", "these", "those", "like",
)


def _score_standalone_opening(clip_words: list) -> dict:
    """Estimate whether a clip opening makes sense without earlier context."""
    if not clip_words:
        return {"score": 0, "reasons": ["no transcript"]}

    opening_words = clip_words[:24]
    opening = " ".join(w["word"] for w in opening_words).strip().lower()
    tokens = [w["word"].strip(".,!?;:\"'()[]{}").lower() for w in opening_words]

    score = 100
    reasons = []

    for phrase in _CONTEXT_DEPENDENT_OPENERS:
        if opening.startswith(phrase):
            score -= 24
            reasons.append(f"context opener: {phrase.strip()}")
            break

    vague_count = sum(token in _VAGUE_OPENING_WORDS for token in tokens[:12])
    if vague_count >= 4:
        score -= 22
        reasons.append("many vague references")
    elif vague_count >= 2:
        score -= 10
        reasons.append("some vague references")

    # A proper noun, number, question, or explicit assertion adds immediate context.
    original_tokens = [w["word"].strip() for w in opening_words[:12]]
    has_named_context = any(t[:1].isupper() for t in original_tokens[1:] if t)
    has_number = _hook_count_numbers(opening) > 0
    has_question = "?" in opening or bool(_hook_contains(opening, _HOOK_QUESTIONS))
    has_assertion = bool(_hook_contains(opening, _HOOK_ASSERTION))
    if has_named_context or has_number or has_question or has_assertion:
        score += 8

    # Very short fragments are usually poor standalone openings.
    if len(tokens) < 8:
        score -= 15
        reasons.append("opening fragment is very short")

    return {"score": max(0, min(100, round(score))), "reasons": reasons}


def _score_payoff(clip_words: list, avg_wps: float) -> dict:
    """Score whether the second half contains a reveal, answer, or consequence."""
    if not clip_words:
        return {"score": 0, "signals": {}}

    midpoint = len(clip_words) // 2
    latter = clip_words[midpoint:]
    latter_text = " ".join(w["word"] for w in latter)
    full_text = " ".join(w["word"] for w in clip_words)

    score = 0
    signals = {}

    payoff_hits = _hook_contains(latter_text, _PAYOFF_PHRASES)
    if payoff_hits:
        score += min(48, 26 + 8 * (len(payoff_hits) - 1))
        signals["payoff_phrase"] = payoff_hits[:3]

    # Reward consequences/revelations in the latter half specifically.
    latter_result = _hook_score_chunk(latter[:40] or latter, latter_text, avg_wps)
    high_value = {"revelation", "stakes", "conflict", "number"}
    latter_categories = high_value.intersection(latter_result["signals"])
    if latter_categories:
        score += 12 * len(latter_categories)
        signals["late_signals"] = sorted(latter_categories)

    # Reward a question in the first third that receives declarative content later.
    first_third = clip_words[:max(1, len(clip_words) // 3)]
    first_text = " ".join(w["word"] for w in first_third)
    if ("?" in first_text or _hook_contains(first_text, _HOOK_QUESTIONS)) and len(latter) >= 15:
        score += 14
        signals["question_answer_shape"] = ["question followed by body"]

    # Reward concrete detail in the payoff, but cap it so number-heavy sections do not dominate.
    number_count = _hook_count_numbers(latter_text)
    if number_count:
        score += min(12, number_count * 4)

    # Penalize clips that repeatedly promise a reveal but never provide one.
    promises = _hook_contains(full_text, ["coming up", "later i'll", "wait until", "stay tuned"])
    if promises and not payoff_hits:
        score -= 20
        signals["unfulfilled_promise"] = promises[:2]

    return {"score": max(0, min(100, round(score))), "signals": signals}


def _score_ending(clip_words: list, end_sec: float, all_words: list,
                  start_times: list = None) -> dict:
    """Score whether the chosen clip ending feels complete rather than abrupt."""
    if not clip_words:
        return {"score": 0, "reasons": ["no transcript"]}

    last = clip_words[-1]
    token = last["word"].strip()
    clean_punctuation = bool(token and token[-1] in ".?!")
    normalized = token.strip(".,!?;:\"'()[]{}").lower()

    score = 45
    reasons = []
    if clean_punctuation:
        score += 40
        reasons.append("ends on sentence punctuation")

    # Find the next transcript word to inspect the pause after the ending.
    if start_times is None:
        start_times = [w["start"] for w in all_words]
    next_index = bisect_left(start_times, last["end"])
    while next_index < len(all_words) and all_words[next_index] is last:
        next_index += 1
    if next_index < len(all_words):
        gap = all_words[next_index]["start"] - last["end"]
        if gap >= 0.65:
            score += 20
            reasons.append("ends before a strong pause")
        elif gap >= 0.35:
            score += 10
            reasons.append("ends before a pause")

    if normalized in _UNFINISHED_ENDINGS:
        score -= 40
        reasons.append(f"ends on unfinished word: {normalized}")

    # If the final transcript word is materially before the video cut, silence is a clean buffer.
    if end_sec - last["end"] >= 0.35:
        score += 8

    return {"score": max(0, min(100, round(score))), "reasons": reasons}
