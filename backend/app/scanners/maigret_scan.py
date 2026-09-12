from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.config import (
    MAIGRET_FULL,
    MAIGRET_MAX_CONNECTIONS,
    MAIGRET_NSFW,
    MAIGRET_PARSE,
    MAIGRET_SITE_TIMEOUT,
    MAIGRET_TIMEOUT,
    MAIGRET_TOP_SITES,
)
from app.detect import (
    derive_username,
    format_tried_handles,
    merge_findings_by_url,
    social_username_candidates,
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
        "Default run uses the top-ranked site slice (MAIGRET_TOP_SITES, default 50) "
        "and skips disabled, NSFW, and .onion sites. Soft-404s still happen. "
        "Set MAIGRET_FULL=1 for the complete enabled list (slower). "
        "Email local-parts with dots try an alphanumeric handle first "
        "(SOCIAL_USERNAME_CANDIDATES). Missing package → unavailable."
    )
    timeout = MAIGRET_TIMEOUT
    heavy = True

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
        handles = social_username_candidates(query)
        if not handles:
            return self._result("skipped", "No username candidate")

        wall = float(os.getenv("MAIGRET_TIMEOUT", self.timeout))
        pad = 5.0 if wall >= 20 else max(0.05, wall * 0.2)
        inner = max(0.05, wall - pad)
        deadline = asyncio.get_running_loop().time() + inner

        tried: list[str] = []
        collected: list[Finding] = []
        runs: list[dict[str, Any]] = []
        timed_out = False
        last_error: str | None = None

        for username in handles:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0.05:
                timed_out = True
                break
            try:
                raw = await asyncio.wait_for(self._search(username, loaded), timeout=remaining)
            except asyncio.TimeoutError:
                timed_out = True
                break
            except Exception as exc:
                last_error = str(exc)
                continue
            tried.append(username)
            collected.extend(findings_from_results(raw.get("results") or {}, username))
            runs.append(
                {
                    "username": username,
                    "checked": raw.get("checked"),
                    "found": raw.get("found"),
                    "subset": raw.get("subset"),
                    "top": raw.get("top"),
                }
            )

        findings = merge_findings_by_url(collected)
        profiles = sum(1 for f in findings if f.kind == "profile")
        tried_label = format_tried_handles(tried or handles)
        raw_out = {
            "usernames": tried,
            "runs": runs,
            "subset": any(r.get("subset") for r in runs),
            "top": next((r.get("top") for r in runs if r.get("top")), None),
        }

        if not tried and timed_out:
            return self._result(
                "timeout",
                f"Timed out after {int(inner)}s · tried {format_tried_handles(handles)}",
                error="timeout",
                raw=raw_out,
            )
        if not tried and last_error:
            return self._result("error", "Maigret failed", error=last_error, raw=raw_out)
        if not tried:
            return self._result("error", "Maigret failed", error=last_error or "no runs")

        summary = (
            f"{profiles} profile(s) for {tried_label}"
            if profiles
            else f"No Maigret hits for {tried_label}"
        )
        if raw_out.get("subset") and raw_out.get("top"):
            summary += f" · top {raw_out.get('top')} sites"
        if timed_out:
            summary += " · later handle(s) timed out"
        return self._result("success", summary, findings=findings, raw=raw_out)

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
        max_conn = int(os.getenv("MAIGRET_MAX_CONNECTIONS", str(MAIGRET_MAX_CONNECTIONS)))
        results = await maigret_search(
            username=username,
            site_dict=site_dict,
            logger=_log,
            query_notify=None,
            timeout=int(max(2, site_timeout)),
            is_parsing_enabled=parse,
            is_enrich_enabled=False,
            id_type="username",
            max_connections=max(2, max_conn),
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
