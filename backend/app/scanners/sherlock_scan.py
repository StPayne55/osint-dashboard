from __future__ import annotations

import asyncio
import os
from typing import Any

from app.config import SHERLOCK_FULL, SHERLOCK_SITE_TIMEOUT, SHERLOCK_TIMEOUT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner

PRIORITY_SITES = [
    "GitHub",
    "GitLab",
    "BitBucket",
    "Reddit",
    "Twitter",
    "X",
    "Instagram",
    "TikTok",
    "YouTube",
    "Twitch",
    "Facebook",
    "LinkedIn",
    "Pinterest",
    "Tumblr",
    "Medium",
    "Dev.to",
    "HackerNews",
    "Steam",
    "Spotify",
    "SoundCloud",
    "Last.fm",
    "Flickr",
    "Behance",
    "Dribbble",
    "Patreon",
    "Keybase",
    "About.me",
    "WordPress",
    "Wikipedia",
    "VK",
    "Telegram",
    "Snapchat",
    "Threads",
    "Bluesky",
    "Mastodon.social",
    "ProductHunt",
    "npm",
    "Docker Hub",
    "LeetCode",
    "Codepen",
    "Replit.com",
    "HackerRank",
    "Kaggle",
    "GoodReads",
    "Letterboxd",
    "Chess.com",
    "Roblox",
    "Pinterest",
    "Quora",
    "SlideShare",
]


class SherlockScanner(Scanner):
    id = "sherlock"
    name = "Sherlock"
    tool = "sherlock-project"
    description = (
        "Looks up a username across social networks using Sherlock's public "
        "site fingerprint database. Returns profile URLs when a page exists."
    )
    accepts = [QueryType.username, QueryType.email, QueryType.name]
    limitations = (
        "Existence checks can false-positive on soft-404 pages. NSFW sites are "
        "excluded unless SHERLOCK_NSFW=1. Default run uses a high-signal site "
        "subset; set SHERLOCK_FULL=1 for the complete list."
    )
    timeout = SHERLOCK_TIMEOUT
    heavy = True

    def available(self) -> bool:
        try:
            import sherlock_project.sherlock  # noqa: F401
            from sherlock_project.sites import SitesInformation  # noqa: F401
        except Exception:
            return False
        return True

    def applicable(self, query: Query) -> bool:
        return bool(query.username or query.username_candidates)

    async def run(self, query: Query) -> ScannerResult:
        if not self.available():
            return self._result(
                "unavailable",
                "sherlock-project is not installed",
                error="pip install sherlock-project",
            )
        username = (query.username or (query.username_candidates[0] if query.username_candidates else "")).lstrip("@")
        if not username:
            return self._result("skipped", "No username candidate")

        try:
            raw = await asyncio.to_thread(self._sherlock, username)
        except Exception as exc:
            return self._result("error", "Sherlock failed", error=str(exc))

        findings = [
            Finding(
                kind="profile",
                title=row["site"],
                value=row["url"],
                url=row["url"],
                extra={"username": username, "status": row.get("status")},
            )
            for row in raw.get("found", [])
            if is_concrete_profile_url(row.get("url"))
        ]
        summary = (
            f"{len(findings)} profile(s) for @{username}"
            if findings
            else f"No Sherlock hits for @{username}"
        )
        if raw.get("subset"):
            summary += " · high-signal site subset"
        return self._result("success", summary, findings=findings, raw=raw)

    def _sherlock(self, username: str) -> dict[str, Any]:
        from sherlock_project.notify import QueryNotify
        from sherlock_project.result import QueryStatus
        from sherlock_project.sherlock import sherlock
        from sherlock_project.sites import SitesInformation

        class Silent(QueryNotify):
            def start(self, message=None):  # noqa: ANN001
                return

            def update(self, result):  # noqa: ANN001
                return

            def finish(self, message=None):  # noqa: ANN001
                return

        nsfw = os.getenv("SHERLOCK_NSFW", "").lower() in {"1", "true", "yes"}
        try:
            sites = SitesInformation()
        except Exception:
            import sherlock_project

            local = os.path.join(
                os.path.dirname(sherlock_project.__file__), "resources", "data.json"
            )
            sites = SitesInformation(local, honor_exclusions=False)
        all_data: dict[str, Any] = {}
        for site in sites:
            name = getattr(site, "name", None)
            info = getattr(site, "information", None)
            if not name or not info:
                continue
            if not nsfw and str(info.get("isNSFW", "")).lower() in {"true", "1", "yes"}:
                continue
            all_data[name] = info

        subset = False
        if SHERLOCK_FULL:
            site_data = all_data
        else:
            wanted = {n.lower(): n for n in PRIORITY_SITES}
            site_data = {}
            for name, info in all_data.items():
                if name.lower() in wanted or name in PRIORITY_SITES:
                    site_data[name] = info
            if len(site_data) < 15:
                # Names drifted — take a stable alphabetical slice plus whatever matched.
                extras = [n for n in sorted(all_data) if n not in site_data][:40]
                for name in extras:
                    site_data[name] = all_data[name]
            subset = True

        results = sherlock(
            username=username,
            site_data=site_data,
            query_notify=Silent(),
            timeout=int(SHERLOCK_SITE_TIMEOUT),
        )
        found: list[dict[str, Any]] = []
        for site_name, data in results.items():
            result = data.get("status")
            url = data.get("url_user") or data.get("url_main")
            status_name = getattr(getattr(result, "status", None), "name", None) or str(
                getattr(result, "status", "")
            )
            claimed = False
            if result is not None and hasattr(QueryStatus, "CLAIMED"):
                claimed = getattr(result, "status", None) == QueryStatus.CLAIMED
            elif "CLAIMED" in str(status_name).upper() or "FOUND" in str(status_name).upper():
                claimed = True
            if claimed and url:
                found.append({"site": site_name, "url": url, "status": status_name})
        return {
            "username": username,
            "checked": len(site_data),
            "found": found,
            "subset": subset,
        }
