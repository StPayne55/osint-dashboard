from __future__ import annotations

import ipaddress
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

from app.models import Finding

PHOTO_KEYS = (
    "image",
    "avatar",
    "photo",
    "photos",
    "picture",
    "pictures",
    "profile_image",
    "profileImage",
    "profile_photo",
    "gravatar",
    "thumbnail",
    "thumbnailUrl",
    "thumbnail_url",
    "photo_url",
    "avatar_url",
    "image_url",
    "picture_url",
)

_PHOTO_KEY_SET = {k.lower() for k in PHOTO_KEYS}
_NEST_KEYS = {"ids", "identity", "profile"}
_URLISH_KEYS = ("url", "value", "src", "href", "image", "avatar", "photo")
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
MAX_PHOTOS = 24


def normalize_photo_url(raw: str | None) -> str | None:
    """Keep only public http(s) URLs. Protocol-relative and http upgrade to https."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or text.startswith(("data:", "javascript:", "file:", "about:")):
        return None
    if text.startswith("//"):
        text = "https:" + text
    if not text.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(text)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS or host.endswith(".onion") or host.endswith(".local"):
        return None
    if parsed.username or parsed.password:
        return None
    if _is_private_host(host):
        return None
    cleaned = urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, ""))
    if len(cleaned) > 2000:
        return None
    return cleaned


def photo_dedupe_key(url: str) -> str:
    """Collapse CDN/query variants so the same avatar is not listed twice."""
    try:
        parsed = urlparse(url)
    except Exception:
        return url.rstrip("/").lower()
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").rstrip("/").lower()
    if host.endswith("gravatar.com") and "/avatar/" in path:
        digest = path.rsplit("/", 1)[-1]
        return f"gravatar:{digest}"
    return f"{host}{path}"


def iter_photo_urls(value: Any, *, depth: int = 0) -> list[str]:
    """Pull http(s) URLs out of Maigret/Gravatar string, list, or {url/value} shapes."""
    if depth > 3 or value is None:
        return []
    found: list[str] = []
    if isinstance(value, str):
        url = normalize_photo_url(value)
        return [url] if url else []
    if isinstance(value, dict):
        for key in _URLISH_KEYS:
            if key in value:
                found.extend(iter_photo_urls(value.get(key), depth=depth + 1))
        return found
    if isinstance(value, (list, tuple)):
        for item in value[:12]:
            found.extend(iter_photo_urls(item, depth=depth + 1))
        return found
    return found


def photos_from_mapping(data: dict[str, Any] | None) -> list[str]:
    """Collect photo URLs from known image/avatar/photo keys (and nested ids)."""
    if not isinstance(data, dict):
        return []
    found: list[str] = []
    for key, value in data.items():
        lowered = str(key).lower()
        if lowered in _PHOTO_KEY_SET:
            found.extend(iter_photo_urls(value))
        elif lowered in _NEST_KEYS and isinstance(value, dict):
            found.extend(photos_from_mapping(value))
    return _unique(found)


def photos_from_extra(extra: dict[str, Any] | None) -> list[str]:
    return photos_from_mapping(extra)


def collect_photo_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Unique ``kind=image`` rows plus safe photo URLs harvested from ``extra``."""
    collected: list[Finding] = []
    seen: set[str] = set()

    def add(title: str, url: str, extra: dict[str, Any] | None = None) -> None:
        normalized = normalize_photo_url(url)
        if not normalized:
            return
        key = photo_dedupe_key(normalized)
        if key in seen or len(collected) >= MAX_PHOTOS:
            return
        seen.add(key)
        collected.append(
            Finding(
                kind="image",
                title=title or "Photo",
                value=normalized,
                url=normalized,
                extra=dict(extra or {}),
            )
        )

    items = list(findings)
    for finding in items:
        if finding.kind != "image":
            continue
        add(finding.title, finding.url or finding.value, finding.extra)
    for finding in items:
        extras = photos_from_extra(finding.extra)
        if not extras:
            continue
        extra = finding.extra or {}
        source = ""
        if isinstance(extra.get("source"), str):
            source = extra["source"]
        elif extra.get("site"):
            source = str(extra["site"])
        title = finding.title or "Photo"
        if finding.kind != "image" and title and not title.lower().endswith(
            ("photo", "photos", "avatar", "image")
        ):
            title = f"{title} photo"
        harvested = {"harvested_from": finding.kind}
        if source:
            harvested["source"] = source
        for url in extras:
            add(title, url, harvested)
    return collected[:MAX_PHOTOS]


def promote_extra_photos(findings: list[Finding]) -> list[Finding]:
    """Append harvested extra photo URLs that are not already image findings."""
    existing = {
        photo_dedupe_key(normalized)
        for finding in findings
        if finding.kind == "image"
        for normalized in [normalize_photo_url(finding.url or finding.value)]
        if normalized
    }
    out = list(findings)
    for photo in collect_photo_findings(findings):
        url = photo.url or photo.value
        key = photo_dedupe_key(url)
        if key in existing:
            continue
        existing.add(key)
        out.append(photo)
    return out


def _unique(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        key = photo_dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


def _is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
