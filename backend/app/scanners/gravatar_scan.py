from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.config import USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner


class GravatarScanner(Scanner):
    id = "gravatar"
    name = "Gravatar"
    tool = "Gravatar public API"
    description = (
        "Resolves the public Gravatar profile and avatar for an email using the "
        "published MD5 hash. No API key."
    )
    accepts = [QueryType.email]
    limitations = (
        "Only accounts that opted into Gravatar appear. Display names and photos "
        "are whatever the owner published."
    )
    timeout = 15.0

    async def run(self, query: Query) -> ScannerResult:
        email = (query.email or "").strip().lower()
        if not email:
            return self._result("skipped", "No email")
        digest = hashlib.md5(email.encode("utf-8"), usedforsecurity=False).hexdigest()
        avatar = f"https://www.gravatar.com/avatar/{digest}?s=256&d=404"
        json_url = f"https://www.gravatar.com/{digest}.json"
        findings: list[Finding] = [
            Finding(
                kind="metadata",
                title="Gravatar hash",
                value=digest,
                url=f"https://www.gravatar.com/{digest}",
            )
        ]
        profile: dict[str, Any] = {}
        has_avatar = False
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as client:
            try:
                img = await client.get(avatar, follow_redirects=True)
                has_avatar = img.status_code == 200
            except Exception:
                has_avatar = False
            try:
                resp = await client.get(json_url, follow_redirects=True)
                if resp.status_code == 200:
                    profile = resp.json()
            except Exception:
                profile = {}

        if has_avatar:
            findings.append(
                Finding(
                    kind="image",
                    title="Gravatar avatar",
                    value=avatar,
                    url=avatar,
                    extra={"hash": digest},
                )
            )
        entry = None
        if isinstance(profile, dict):
            entries = profile.get("entry") or []
            if entries:
                entry = entries[0]
        if entry:
            display = entry.get("displayName") or entry.get("preferredUsername")
            if display:
                findings.append(Finding(kind="metadata", title="Display name", value=str(display)))
            if entry.get("aboutMe"):
                findings.append(Finding(kind="note", title="About", value=str(entry["aboutMe"])[:500]))
            if entry.get("currentLocation"):
                findings.append(
                    Finding(kind="metadata", title="Location (self-published)", value=str(entry["currentLocation"]))
                )
            for acc in entry.get("accounts") or []:
                url = acc.get("url")
                profile_url = url if is_concrete_profile_url(url if isinstance(url, str) else None) else None
                findings.append(
                    Finding(
                        kind="profile" if profile_url else "note",
                        title=str(acc.get("shortname") or acc.get("domain") or "account"),
                        value=str(acc.get("display") or url or ""),
                        url=profile_url,
                    )
                )
            for im in entry.get("ims") or []:
                findings.append(
                    Finding(
                        kind="metadata",
                        title=f"IM ({im.get('type')})",
                        value=str(im.get("value") or ""),
                    )
                )
            for url in entry.get("urls") or []:
                findings.append(
                    Finding(
                        kind="link",
                        title=str(url.get("title") or "Profile URL"),
                        value=str(url.get("value") or ""),
                        url=url.get("value"),
                    )
                )
        summary = (
            "Public Gravatar profile found"
            if entry or has_avatar
            else "No public Gravatar profile"
        )
        return self._result(
            "success",
            summary,
            findings=findings if (entry or has_avatar) else findings[:1],
            raw={"hash": digest, "has_avatar": has_avatar, "profile": entry},
        )
