from __future__ import annotations

from urllib.parse import urlparse

# Paths that are a site homepage / marketing page, not a person profile.
_HOME_SEGMENTS = {
    "",
    "about",
    "home",
    "index",
    "index.html",
    "index.htm",
    "login",
    "signup",
    "register",
    "welcome",
    "www",
}


def is_concrete_profile_url(url: str | None) -> bool:
    """True only when *url* has a path beyond the registrable-domain homepage.

    ``https://instagram.com`` and ``https://instagram.com/`` are not profiles.
    ``https://instagram.com/someuser`` and Sherlock/Maigret hits are.
    """
    if not url or not isinstance(url, str):
        return False
    text = url.strip()
    if not text:
        return False
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return False
    if len(parts) == 1 and parts[0].lower() in _HOME_SEGMENTS:
        return False
    return True
