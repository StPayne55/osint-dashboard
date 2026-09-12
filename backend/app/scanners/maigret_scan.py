from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.config import (
    MAIGRET_FULL,
    MAIGRET_NSFW,
    MAIGRET_PARSE,
    MAIGRET_SITE_TIMEOUT,
    MAIGRET_TIMEOUT,
    MAIGRET_TOP_SITES,
)
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner

_NSFW_TAGS = ("porn", "xxx", "webcam", "erotic")
_PHOTO_KEYS = ("image", "avatar", "photo", "picture", "profile_image", "gravatar")
_NAME_KEYS = ("fullname", "full_name", "name", "display_name", "username")

_log = logging.getLogger("osint.maigret")
_log.setLevel(logging.ERROR)
_log.propagate = False


def _load_maigret() -> tuple[Any, Any] | None:
    try:
        from maigret import search as maigret_search
        from maigret.sites import MaigretDatabase
    except Exception:
        return None
    return maigret_search, MaigretDatabase


def derive_username(query: Query) -> str | None:
    if query.username:
        return query.username.lstrip("@")
    if query.username_candidates:
        return query.username_candidates[0].lstrip("@")
    if query.email:
        return query.email.split("@", 1)[0]
    return None


def _status_found(status: Any) -> bool:
    if status is None:
        return False
    check = getattr(status, "is_found", None)
    if callable(check):
        try:
            return bool(check())
        except Exception:
            return False
    name = str(getattr(status, "status", status) or "")
    return name.lower() in {"claimed", "found"}


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def findings_from_results(results: dict[str, Any], username: str) -> list[Finding]:
    """Turn Maigret result dicts (or test doubles) into report findings."""
    findings: list[Finding] = []
    seen: set[str] = set()

    def add(finding: Finding) -> None:
        key = f"{finding.kind}|{finding.title}|{finding.value}|{finding.url or ''}"
        if key in seen:
            return
        seen.add(key)
        findings.append(finding)

    for site_name, row in (results or {}).items():
        if not isinstance(row, dict) and not hasattr(row, "get"):
            continue
        if _row_get(row, "is_similar"):
            continue
        status = _row_get(row, "status")
        claimed = _status_found(status) or bool(_row_get(row, "found"))
        if not claimed:
            continue
        url = _row_get(row, "url_user") or getattr(status, "site_url_user", None)
        if not is_concrete_profile_url(url if isinstance(url, str) else None):
            continue
        ids_data = _row_get(row, "ids_data") or getattr(status, "ids_data", None) or {}
        if not isinstance(ids_data, dict):
            ids_data = {}
        tags = list(_row_get(row, "tags") or getattr(status, "tags", None) or [])
        title = str(_row_get(row, "sitename") or site_name)
        extra: dict[str, Any] = {"username": username}
        if tags:
            extra["tags"] = [str(t) for t in tags[:12]]
        display = next((str(ids_data[k]) for k in _NAME_KEYS if ids_data.get(k)), None)
        if display:
            extra["display_name"] = display
        slim_ids = {
            k: v
            for k, v in ids_data.items()
            if v not in (None, "", [], {}) and k in {*_NAME_KEYS, *_PHOTO_KEYS, "bio", "location"}
        }
        if slim_ids:
            extra["ids"] = slim_ids
        add(
            Finding(
                kind="profile",
                title=title,
                value=str(url),
                url=str(url),
                extra=extra,
            )
        )
        photo = next((ids_data.get(k) for k in _PHOTO_KEYS if ids_data.get(k)), None)
        if isinstance(photo, str) and photo.startswith(("http://", "https://")):
            add(
                Finding(
                    kind="image",
                    title=f"{title} photo",
                    value=photo,
                    url=photo,
                    extra={"username": username, "site": title},
                )
            )
    return findings


class MaigretScanner(Scanner):
    id = "maigret"
    name = "Maigret"
    tool = "maigret"
    description = (
        "Username dossier across a large public site database. Returns profile "
        "URLs (and public display names / photos when parsing is on) without API keys."
    )
    accepts = [QueryType.username, QueryType.email, QueryType.name]
    limitations = (
        "Default run uses the top-ranked site slice (MAIGRET_TOP_SITES, default 200) "
        "and skips disabled, NSFW, and .onion sites. Soft-404s still happen. "
        "Set MAIGRET_FULL=1 for the complete enabled list (slower). "
        "Missing package → unavailable."
    )
    timeout = MAIGRET_TIMEOUT

    def available(self) -> bool:
        return _load_maigret() is not None

    def applicable(self, query: Query) -> bool:
        return bool(derive_username(query))

    async def run(self, query: Query) -> ScannerResult:
        loaded = _load_maigret()
        if loaded is None:
            return self._result(
                "unavailable",
                "maigret is not installed",
                error="pip install maigret",
            )
        username = derive_username(query)
        if not username:
            return self._result("skipped", "No username candidate")

        wall = float(os.getenv("MAIGRET_TIMEOUT", self.timeout))
        pad = 5.0 if wall >= 20 else max(0.05, wall * 0.2)
        inner = max(0.05, wall - pad)
        try:
            raw = await asyncio.wait_for(self._search(username, loaded), timeout=inner)
        except asyncio.TimeoutError:
            return self._result(
                "timeout",
                f"Timed out after {int(inner)}s",
                error="timeout",
            )
        except Exception as exc:
            return self._result("error", "Maigret failed", error=str(exc))

        findings = findings_from_results(raw.get("results") or {}, username)
        profiles = sum(1 for f in findings if f.kind == "profile")
        summary = (
            f"{profiles} profile(s) for @{username}"
            if profiles
            else f"No Maigret hits for @{username}"
        )
        if raw.get("subset"):
            summary += f" · top {raw.get('top')} sites"
        return self._result("success", summary, findings=findings, raw=raw)

    async def _search(self, username: str, loaded: tuple[Any, Any]) -> dict[str, Any]:
        maigret_search, database_cls = loaded
        # load_from_path is sync file I/O; search() itself is a real aiohttp coroutine.
        db = await asyncio.to_thread(_database, database_cls)
        top, subset, excluded = _site_limits()
        site_dict = db.ranked_sites_dict(
            top=top,
            disabled=False,
            id_type="username",
            excluded_tags=excluded,
        )
        site_dict = {
            name: site
            for name, site in site_dict.items()
            if ".onion" not in f"{getattr(site, 'url', '')} {getattr(site, 'url_main', '')}".lower()
        }
        parse = os.getenv("MAIGRET_PARSE", "1" if MAIGRET_PARSE else "0").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        site_timeout = float(os.getenv("MAIGRET_SITE_TIMEOUT", str(MAIGRET_SITE_TIMEOUT)))
        results = await maigret_search(
            username=username,
            site_dict=site_dict,
            logger=_log,
            query_notify=None,
            timeout=int(max(2, site_timeout)),
            is_parsing_enabled=parse,
            is_enrich_enabled=False,
            id_type="username",
            max_connections=40,
            no_progressbar=True,
            retries=0,
            check_domains=False,
        )
        compact = []
        for name, row in (results or {}).items():
            status = _row_get(row, "status")
            if not (_status_found(status) or _row_get(row, "found")):
                continue
            url = _row_get(row, "url_user") or getattr(status, "site_url_user", None)
            compact.append({"site": name, "url": url, "found": True})
        return {
            "username": username,
            "checked": len(site_dict),
            "found": compact,
            "results": results,
            "top": top if subset else None,
            "subset": subset,
            "parse": parse,
        }


def _site_limits() -> tuple[int, bool, list[str]]:
    full = os.getenv("MAIGRET_FULL", "").lower() in {"1", "true", "yes"} or MAIGRET_FULL
    nsfw = os.getenv("MAIGRET_NSFW", "").lower() in {"1", "true", "yes"} or MAIGRET_NSFW
    excluded = [] if nsfw else list(_NSFW_TAGS)
    if full:
        return 10**9, False, excluded
    top = int(os.getenv("MAIGRET_TOP_SITES", str(MAIGRET_TOP_SITES)))
    return max(20, top), True, excluded


def _database(database_cls: Any) -> Any:
    import maigret

    path = os.path.join(os.path.dirname(maigret.__file__), "resources", "data.json")
    return database_cls().load_from_path(path)
