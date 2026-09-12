from __future__ import annotations

from app.config import SOCIALSCAN_TIMEOUT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner


class SocialscanScanner(Scanner):
    id = "socialscan"
    name = "Socialscan"
    tool = "socialscan"
    description = (
        "Checks whether an email or username is available or already taken on a "
        "small set of platforms (GitHub, GitLab, Instagram, Tumblr, …) using "
        "official signup/validation endpoints."
    )
    accepts = [QueryType.email, QueryType.username, QueryType.name]
    limitations = (
        "Fewer platforms than Sherlock. 'Taken' means the identifier is registered "
        "or reserved — not a profile URL. Some platforms have dropped their public checkers."
    )
    timeout = SOCIALSCAN_TIMEOUT
    heavy = True

    def available(self) -> bool:
        try:
            from socialscan.util import execute_queries  # noqa: F401
        except Exception:
            return False
        return True

    def applicable(self, query: Query) -> bool:
        return bool(query.email or query.username or query.username_candidates)

    async def run(self, query: Query) -> ScannerResult:
        if not self.available():
            return self._result(
                "unavailable",
                "socialscan is not installed",
                error="pip install socialscan",
            )
        from socialscan.util import execute_queries

        try:
            from socialscan.util import Platforms
        except Exception:
            from socialscan.platforms import Platforms  # type: ignore

        queries: list[str] = []
        if query.email:
            queries.append(query.email)
        handle = query.username or (query.username_candidates[0] if query.username_candidates else None)
        if handle and handle not in queries:
            queries.append(handle)
        if not queries:
            return self._result("skipped", "No email or username")

        platforms = list(Platforms)
        try:
            results = await execute_queries(queries, platforms)
        except Exception as exc:
            return self._result("error", "socialscan failed", error=str(exc))

        findings: list[Finding] = []
        raw_rows = []
        for row in results or []:
            platform = getattr(row, "platform", None)
            platform_name = getattr(platform, "name", None) or str(platform)
            available = bool(getattr(row, "available", False))
            success = bool(getattr(row, "success", False))
            valid = bool(getattr(row, "valid", True))
            message = str(getattr(row, "message", "") or "")
            link = getattr(row, "link", None)
            q = str(getattr(row, "query", "") or "")
            raw_rows.append(
                {
                    "platform": platform_name,
                    "query": q,
                    "available": available,
                    "success": success,
                    "valid": valid,
                    "message": message,
                    "link": link,
                }
            )
            if not success:
                continue
            if valid and not available:
                url = str(link) if is_concrete_profile_url(link if isinstance(link, str) else None) else None
                findings.append(
                    Finding(
                        kind="profile" if url else "note",
                        title=str(platform_name),
                        value=f"{q} is taken on {platform_name} (registration, not a profile URL)"
                        if not url
                        else f"{q} is taken",
                        url=url,
                        extra={"message": message, "query": q},
                    )
                )

        summary = (
            f"{len(findings)} taken identifier(s)"
            if findings
            else "No platform reported the identifier as taken"
        )
        return self._result("success", summary, findings=findings, raw=raw_rows)
