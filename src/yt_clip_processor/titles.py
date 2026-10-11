"""Titles stage of the video processor."""



def _sanitize_filename(text: str, max_len: int = 60) -> str:
    """
    Turn a chunk of transcript text into a safe filename fragment.
    Strips characters illegal on Windows filesystems (relevant since these
    scripts commonly run under WSL against /mnt/c) and collapses whitespace.
    """
    import re
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)          # illegal on Windows
    text = text.strip(" .,;:!?-\u2026")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].strip()
    return text or "clip"


_GROQ_LAST_CALL_TS = [0.0]     # module-level mutable box: last successful call time


_GROQ_MIN_INTERVAL = 2.2       # seconds between calls — keeps us safely under 30 req/min


def _groq_generate_title(text: str, max_words: int = 8) -> str:
    """
    Ask a free Groq-hosted LLM (llama-3.1-8b-instant) for a short, punchy
    TikTok-style title summarizing this clip's transcript — an actual
    summary rather than just the leading words.

    Returns "" on ANY failure (no API key set, network error, rate limit,
    bad response, etc.) so callers can fall back to the local heuristic
    title generator without ever crashing the pipeline over a title.

    Self-throttles to stay under Groq's free-tier ~30 requests/minute cap:
    blocks briefly before firing if called again too soon.
    """
    import os, time

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not text.strip():
        return ""

    try:
        import requests
    except ImportError:
        print("    \u26a0\ufe0f  'requests' not installed (pip install requests) \u2014 skipping LLM title")
        return ""

    elapsed = time.time() - _GROQ_LAST_CALL_TS[0]
    if elapsed < _GROQ_MIN_INTERVAL:
        time.sleep(_GROQ_MIN_INTERVAL - elapsed)

    prompt = (
        "You write short, punchy TikTok video titles summarizing transcript clips. "
        f"Write exactly ONE title, {max_words} words or fewer. "
        "No quotes, no hashtags, no emoji, no trailing punctuation, no preamble \u2014 "
        "output ONLY the title text itself.\n\n"
        f"Transcript:\n{text[:1500]}"
    )

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 30,
                "temperature": 0.5,
            },
            timeout=15,
        )
        _GROQ_LAST_CALL_TS[0] = time.time()

        if resp.status_code == 429:
            print("    \u26a0\ufe0f  Groq rate limit hit \u2014 falling back to local title")
            return ""
        resp.raise_for_status()

        title = resp.json()["choices"][0]["message"]["content"].strip()
        return _sanitize_filename(title) if title else ""
    except Exception as e:
        print(f"    \u26a0\ufe0f  Groq title generation failed ({e}) \u2014 falling back to local title")
        return ""


def generate_clip_title(text: str, max_words: int = 10, max_len: int = 60, use_llm: bool = True) -> str:
    """
    Derive a short, TikTok-style title from a clip's transcript text.

    If use_llm is True and GROQ_API_KEY is set in the environment, this asks
    a free Groq-hosted LLM for a real summary-style title. Otherwise (or if
    the API call fails for any reason) it falls back to a purely local
    heuristic: the leading words of the transcript, trimmed to a clean
    word/character boundary. Either way the result is sanitized for use as
    a filename — on TikTok, the uploaded file's name becomes the video's
    title/caption, so this is what viewers will see.
    """
    if not text:
        return "clip"

    if use_llm:
        llm_title = _groq_generate_title(text, max_words=max_words)
        if llm_title:
            return llm_title
    words = text.split()
    snippet = " ".join(words[:max_words])
    return _sanitize_filename(snippet, max_len=max_len)
