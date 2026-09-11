from __future__ import annotations

import httpx

from app.config import HIBP_API_KEY, USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner


class HibpScanner(Scanner):
    id = "hibp"
    name = "Have I Been Pwned"
    tool = "HIBP v3 API"
    description = (
        "Optional. Lists public breach titles associated with an email if "
        "HIBP_API_KEY is set. No key → skipped, no fabricated breaches."
    )
    accepts = [QueryType.email]
    optional_key = "HIBP_API_KEY"
    limitations = (
        "Requires a paid/free HIBP API key. Without it this module is skipped. "
        "Never queries stolen-credential marketplaces."
    )
    timeout = 15.0

    def available(self) -> bool:
        return bool(HIBP_API_KEY)

    async def run(self, query: Query) -> ScannerResult:
        if not HIBP_API_KEY:
            return self._result(
                "skipped",
                "HIBP_API_KEY not set — optional module skipped",
                findings=[
                    Finding(
                        kind="link",
                        title="Check this email on HIBP yourself",
                        value=query.email or "",
                        url=f"https://haveibeenpwned.com/account/{query.email}" if query.email else "https://haveibeenpwned.com/",
                    )
                ],
            )
        email = query.email
        if not email:
            return self._result("skipped", "No email")
        url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
        headers = {
            "hibp-api-key": HIBP_API_KEY,
            "User-Agent": USER_AGENT,
        }
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                resp = await client.get(url, params={"truncateResponse": "false"})
        except Exception as exc:
            return self._result("error", "HIBP request failed", error=str(exc))
        if resp.status_code == 404:
            return self._result("success", "HIBP reports no breaches for this email", findings=[])
        if resp.status_code == 401:
            return self._result("error", "HIBP rejected the API key", error="401 unauthorized")
        if resp.status_code != 200:
            return self._result("error", f"HIBP HTTP {resp.status_code}", error=resp.text[:300])
        breaches = resp.json() if resp.content else []
        findings = []
        for row in breaches:
            findings.append(
                Finding(
                    kind="breach",
                    title=str(row.get("Title") or row.get("Name")),
                    value=str(row.get("Domain") or ""),
                    url=f"https://haveibeenpwned.com/breach/{row.get('Name')}" if row.get("Name") else None,
                    extra={
                        "breach_date": row.get("BreachDate"),
                        "data_classes": row.get("DataClasses"),
                    },
                )
            )
        return self._result(
            "success",
            f"{len(findings)} breach record(s)",
            findings=findings,
            raw=breaches,
        )
