"""Tune SpiderFoot Account Finder for Render Starter wall clocks.

v4 ``sfp_accounts.handleEvent`` runs a WhatsMyName *distrust sweep* against
every site (``checkSites(random_garbage_user)``) before the real username.
With ~715 sites, ``_fetchtimeout=5`` and a handful of threads, that cold pass
alone routinely burns 180–300s — so a 300s runner timeout salvages only the
seed USERNAME event.

WhatsMyName ``e_code`` / ``e_string`` already gate false positives, so the
sweep is optional. This helper:

* skips distrust unless ``SPIDERFOOT_SKIP_DISTRUST=0``
* caps the site list (default 120), prioritizing Sherlock/Maigret overlap
* prefers a bundled ``wmn-data.json`` / high-signal slice over a live GitHub fetch
* can pre-bake ``sfaccounts_state_v2`` as ``None`` so an un-skipped cold start
  still does not re-sweep

Imported by the patched ``sfp_accounts.py`` (copied next to ``sf.py``).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# Default on: WMN existence codes/strings already reject random hits.
DEFAULT_SKIP_DISTRUST = True
DEFAULT_MAX_SITES = 120

# Sherlock PRIORITY_SITES plus WMN's real names (GitHub (User), X, …).
# Matching is case-insensitive; names of length >= 4 also match a "Name (" prefix.
PRIORITY_SITES = (
    "GitHub (User)",
    "GitHub (Gists)",
    "GitLab",
    "Bitbucket",
    "Gitea",
    "X",
    "Twitter",
    "Instagram",
    "TikTok",
    "YouTube User2",
    "YouTube User",
    "YouTube Channel",
    "Twitch",
    "Facebook",
    "Reddit",
    "Pinterest",
    "tumblr",
    "Medium",
    "dev.to",
    "Hacker News",
    "Steam",
    "Spotify",
    "SoundCloud",
    "Last.fm",
    "Flickr",
    "Behance",
    "Dribbble",
    "Patreon",
    "Keybase",
    "about.me",
    "VK",
    "Telegram",
    "Snapchat",
    "Threads",
    "Bluesky Username",
    "Producthunt",
    "npm",
    "Docker Hub (User)",
    "LeetCode",
    "CodePen",
    "Replit",
    "HackerRank",
    "Kaggle",
    "Letterboxd",
    "Chess.com",
    "Roblox",
    "Quora",
    "Slideshare",
    "WordPress.com (Public)",
    "WordPress.org (Profiles)",
    "Mastodon.online",
    "HackerOne",
    "TryHackMe",
    "Linktree",
    "Ko-Fi",
    "Substack",
    "Hashnode",
    "Disqus",
    "Vimeo",
    "Dailymotion",
    "Imgur",
    "Wattpad",
    "MyAnimeList",
    "AniList",
    "Duolingo",
    "Strava",
    "Xbox Gamertag",
    "Playstation Network",
    "Codecademy",
    "freeCodeCamp",
    "Codewars",
    "Codeforces",
    "Gravatar",
    "GitHub",
    "YouTube",
    "Docker Hub",
    "About.me",
    "LinkedIn",
    "Wikipedia",
)

PREFERRED_CATS = (
    "social",
    "coding",
    "tech",
    "blog",
    "images",
    "video",
    "music",
    "news",
    "business",
)
NSFW_CAT = "xx nsfw xx"

DISTRUST_CACHE_LABEL = "sfaccounts_state_v2"
SITES_CACHE_LABEL = "sfaccountsv2"


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def should_skip_distrust() -> bool:
    """True unless SPIDERFOOT_SKIP_DISTRUST is an explicit off value."""
    raw = os.getenv("SPIDERFOOT_SKIP_DISTRUST")
    if raw is None or not str(raw).strip():
        return DEFAULT_SKIP_DISTRUST
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def accounts_max_sites() -> int:
    """0 or negative means unlimited (full WhatsMyName list)."""
    raw = (os.getenv("SPIDERFOOT_ACCOUNTS_MAX_SITES") or str(DEFAULT_MAX_SITES)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_SITES


def allow_nsfw_sites() -> bool:
    return _flag("SPIDERFOOT_ACCOUNTS_NSFW", False)


def cache_filename(label: str) -> str:
    return hashlib.sha224(label.encode("utf-8")).hexdigest()


def _site_name(site: dict[str, Any]) -> str:
    return str(site.get("name") or "").strip()


def _site_cat(site: dict[str, Any]) -> str:
    return str(site.get("cat") or site.get("category") or "").strip().lower()


def _priority_rank(name: str) -> int | None:
    lower = name.lower()
    for index, pref in enumerate(PRIORITY_SITES):
        needle = pref.lower()
        if lower == needle:
            return index
        if len(needle) >= 4 and (
            lower.startswith(f"{needle} (") or lower.startswith(f"{needle} ")
        ):
            return index
    return None


def cap_sites(
    sites: list[dict[str, Any]],
    max_sites: int | None = None,
    *,
    allow_nsfw: bool | None = None,
) -> list[dict[str, Any]]:
    """Keep a high-signal prefix of *sites*. ``max_sites<=0`` keeps all (minus NSFW)."""
    limit = accounts_max_sites() if max_sites is None else int(max_sites)
    nsfw_ok = allow_nsfw_sites() if allow_nsfw is None else allow_nsfw
    filtered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for site in sites:
        name = _site_name(site)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        if not nsfw_ok and _site_cat(site) == NSFW_CAT:
            continue
        seen.add(key)
        filtered.append(site)

    if limit <= 0 or len(filtered) <= limit:
        return filtered

    ranked: list[tuple[int, dict[str, Any]]] = []
    rest: list[dict[str, Any]] = []
    for site in filtered:
        rank = _priority_rank(_site_name(site))
        if rank is None:
            rest.append(site)
        else:
            ranked.append((rank, site))
    ranked.sort(key=lambda item: item[0])
    selected = [site for _, site in ranked]
    if len(selected) >= limit:
        return selected[:limit]

    preferred = [s for s in rest if _site_cat(s) in PREFERRED_CATS]
    other = [s for s in rest if s not in preferred]
    for site in preferred + other:
        selected.append(site)
        if len(selected) >= limit:
            break
    return selected[:limit]


def parse_wmn_sites(content: str) -> list[dict[str, Any]]:
    data = json.loads(content)
    raw = data.get("sites") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ValueError("WhatsMyName JSON has no sites list")
    sites: list[dict[str, Any]] = []
    for site in raw:
        if not isinstance(site, dict):
            continue
        if site.get("valid", True) is False:
            continue
        if not (site.get("uri_check") or site.get("check_uri")):
            continue
        sites.append(site)
    return sites


def load_sites(content: str, max_sites: int | None = None) -> list[dict[str, Any]]:
    return cap_sites(parse_wmn_sites(content), max_sites=max_sites)


def _candidate_wmn_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = (os.getenv("SPIDERFOOT_WMN_JSON") or "").strip()
    if explicit:
        paths.append(Path(explicit))
    home = Path(os.getenv("SPIDERFOOT_HOME", "/opt/spiderfoot") or "/opt/spiderfoot")
    here = Path(__file__).resolve().parent
    paths.extend(
        (
            home / "data" / "wmn-data.json",
            home / "data" / "wmn-priority.json",
            here / "wmn-priority.json",
            here / "wmn-data.json",
            here / "data" / "wmn-data.json",
        )
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def bundled_wmn_content() -> str | None:
    for path in _candidate_wmn_paths():
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if text.strip():
                    return text
        except OSError:
            continue
    return None


def bake_spiderfoot_cache(
    cache_dir: Path | str,
    wmn_content: str | None = None,
) -> list[Path]:
    """Write ``sfaccounts_state_v2=None`` and optional ``sfaccountsv2`` list."""
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    state = root / cache_filename(DISTRUST_CACHE_LABEL)
    state.write_text("None", encoding="utf-8")
    written.append(state)
    blob = wmn_content if wmn_content is not None else bundled_wmn_content()
    if blob:
        sites_path = root / cache_filename(SITES_CACHE_LABEL)
        sites_path.write_text(blob, encoding="utf-8")
        written.append(sites_path)
    return written


def simulate_username_lookup(
    username: str,
    sites: list[dict[str, Any]],
    *,
    skip_distrust: bool | None = None,
    check_sites=None,
) -> tuple[list[str], list[str]]:
    """Stand-in for patched ``handleEvent`` on a USERNAME event.

    Returns ``(check_usernames, account_hits)``. ``check_sites(user, sites)``
    should return hit labels the way SF ``checkSites`` does.
    """
    skip = should_skip_distrust() if skip_distrust is None else skip_distrust
    calls: list[str] = []

    def _default_check(user: str, site_list: list[dict[str, Any]]) -> list[str]:
        # Deterministic stand-in: first coding/social site is a hit.
        for site in site_list:
            tmpl = site.get("uri_pretty") or site.get("uri_check") or site.get("check_uri")
            if not tmpl:
                continue
            try:
                url = str(tmpl).format(account=user)
            except (KeyError, IndexError, ValueError):
                continue
            cat = site.get("cat") or site.get("category") or "unknown"
            return [f"{site['name']} (Category: {cat})\n<SFURL>{url}</SFURL>"]
        return []

    checker = check_sites or _default_check
    working = list(sites)
    if not skip:
        randuser = "x7k2m9q1ab"  # 10-char garbage, same length as upstream
        calls.append(randuser)
        hits = checker(randuser, working)
        if hits:
            bad = {hit.split(" (Category:")[0] for hit in hits}
            working = [s for s in working if _site_name(s) not in bad]
    calls.append(username)
    accounts = checker(username, working)
    return calls, accounts
