from __future__ import annotations

from typing import Any

import httpx

from app.config import ABSTRACT_PHONE_API_KEY, USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner


class AbstractPhoneScanner(Scanner):
    id = "abstract_phone"
    name = "AbstractAPI phone"
    tool = "AbstractAPI Phone Validation"
    description = (
        "Optional. Validates a number and returns country, location, type, and "
        "carrier when ABSTRACT_PHONE_API_KEY is set. Does not return a subscriber name."
    )
    accepts = [QueryType.phone]
    optional_key = "ABSTRACT_PHONE_API_KEY"
    limitations = (
        "Skipped without a key. This is validation metadata, not CNAM — it will "
        "not name the person who owns the number."
    )
    timeout = 15.0

    def available(self) -> bool:
        return bool(ABSTRACT_PHONE_API_KEY)

    async def run(self, query: Query) -> ScannerResult:
        if not ABSTRACT_PHONE_API_KEY:
            return self._result(
                "skipped",
                "ABSTRACT_PHONE_API_KEY not set — optional validation skipped",
            )
        number = query.phone_e164 or query.raw
        url = "https://phonevalidation.abstractapi.com/v1/"
        try:
            async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(
                    url,
                    params={"api_key": ABSTRACT_PHONE_API_KEY, "phone": number},
                )
                data = resp.json()
        except Exception as exc:
            return self._result("error", "AbstractAPI phone lookup failed", error=str(exc))

        if resp.status_code == 401 or (isinstance(data, dict) and data.get("error")):
            err = data.get("error") if isinstance(data, dict) else None
            message = ""
            if isinstance(err, dict):
                message = str(err.get("message") or err)
            elif err:
                message = str(err)
            return self._result(
                "error",
                "AbstractAPI phone error",
                error=message or f"HTTP {resp.status_code}",
                raw=data,
            )

        findings = _findings_from_abstract(data if isinstance(data, dict) else {})
        return self._result(
            "success",
            "AbstractAPI validation complete" if findings else "AbstractAPI returned no fields",
            findings=findings,
            raw=data,
        )


def _findings_from_abstract(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if data.get("phone"):
        findings.append(Finding(kind="phone", title="AbstractAPI number", value=str(data["phone"])))
    if data.get("valid") is False:
        findings.append(Finding(kind="note", title="Validity", value="AbstractAPI marked this number invalid"))
    elif data.get("valid") is True:
        findings.append(Finding(kind="metadata", title="Validity", value="valid"))

    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    if fmt.get("international"):
        findings.append(
            Finding(kind="metadata", title="International format", value=str(fmt["international"]))
        )
    if fmt.get("local"):
        findings.append(Finding(kind="metadata", title="Local format", value=str(fmt["local"])))

    country = data.get("country") if isinstance(data.get("country"), dict) else {}
    if country.get("name"):
        findings.append(Finding(kind="metadata", title="Country", value=str(country["name"])))
    if data.get("location"):
        findings.append(Finding(kind="metadata", title="Region", value=str(data["location"])))
    if data.get("type"):
        findings.append(Finding(kind="metadata", title="Line type", value=str(data["type"])))
    if data.get("carrier"):
        findings.append(Finding(kind="metadata", title="Carrier", value=str(data["carrier"])))
    return findings
