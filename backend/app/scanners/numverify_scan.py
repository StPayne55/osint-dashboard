from __future__ import annotations

import httpx

from app.config import NUMVERIFY_API_KEY
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner


class NumverifyScanner(Scanner):
    id = "numverify"
    name = "Numverify"
    tool = "Numverify API"
    description = (
        "Optional carrier/line validation via apilayer Numverify when "
        "NUMVERIFY_API_KEY is set. Redundant with the built-in phonenumbers module."
    )
    accepts = [QueryType.phone]
    optional_key = "NUMVERIFY_API_KEY"
    limitations = "Skipped without a key. Free tier is rate-limited."
    timeout = 15.0

    def available(self) -> bool:
        return bool(NUMVERIFY_API_KEY)

    async def run(self, query: Query) -> ScannerResult:
        if not NUMVERIFY_API_KEY:
            return self._result(
                "skipped",
                "NUMVERIFY_API_KEY not set — using built-in phone metadata instead",
            )
        number = query.phone_e164 or query.raw
        url = "https://apilayer.net/api/validate"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(
                    url,
                    params={"access_key": NUMVERIFY_API_KEY, "number": number},
                )
                data = resp.json()
        except Exception as exc:
            return self._result("error", "Numverify failed", error=str(exc))
        if not data.get("valid") and data.get("error"):
            return self._result("error", "Numverify error", error=str(data.get("error")), raw=data)
        findings = []
        for key in ("number", "local_format", "international_format", "country_name", "location", "carrier", "line_type"):
            if data.get(key):
                findings.append(Finding(kind="metadata", title=key.replace("_", " "), value=str(data[key])))
        return self._result(
            "success",
            "Numverify lookup complete" if findings else "Numverify returned no fields",
            findings=findings,
            raw=data,
        )
