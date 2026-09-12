from __future__ import annotations

from typing import Any

import httpx

from app.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner

# Empty CNAM is a successful lookup with no name — not a scanner failure.
EMPTY_CNAM_NOTE = (
    "No caller name on file (common for mobile numbers — CNAM often blank)."
)


class TwilioLookupScanner(Scanner):
    id = "twilio"
    name = "Twilio Lookup"
    tool = "Twilio Lookup v2"
    description = (
        "Optional. Requests Twilio Lookup caller name (US CNAM) and line-type "
        "intelligence when TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are set."
    )
    accepts = [QueryType.phone]
    optional_key = "TWILIO_ACCOUNT_SID"
    limitations = (
        "Skipped without Twilio credentials. Caller name is a paid Lookup add-on "
        "and is often empty for cell numbers. Empty CNAM means no caller name on "
        "file — not an error. This module never invents a subscriber name."
    )
    timeout = 15.0

    def available(self) -> bool:
        return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)

    async def run(self, query: Query) -> ScannerResult:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            return self._result(
                "skipped",
                "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set — no CNAM lookup",
            )
        number = query.phone_e164 or query.raw
        url = f"https://lookups.twilio.com/v2/PhoneNumbers/{number}"
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        params = {"Fields": "caller_name,line_type_intelligence"}
        try:
            async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(url, params=params, auth=auth)
                data = resp.json()
        except Exception as exc:
            return self._result("error", "Twilio Lookup failed", error=str(exc))

        if resp.status_code == 401:
            return self._result("error", "Twilio rejected the credentials", error="HTTP 401", raw=data)
        if resp.status_code == 404:
            return self._result("empty", "Twilio has no record for this number", raw=data)
        if resp.status_code >= 400:
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error_message") or "")
            return self._result(
                "error",
                f"Twilio Lookup HTTP {resp.status_code}",
                error=message or f"HTTP {resp.status_code}",
                raw=data,
            )

        findings, caller = _findings_from_lookup(data if isinstance(data, dict) else {})
        cnam_error = next(
            (
                f
                for f in findings
                if f.title.lower().startswith("caller name") and "error" in f.value.lower()
            ),
            None,
        )
        if caller:
            return self._result("success", f"CNAM: {caller}", findings=findings, raw=data)
        if cnam_error:
            return self._result(
                "error",
                "Twilio CNAM add-on error",
                findings=findings,
                error=cnam_error.value,
                raw=data,
            )
        if any(f.value == EMPTY_CNAM_NOTE for f in findings):
            summary = EMPTY_CNAM_NOTE
        else:
            summary = "Twilio line metadata (no CNAM field)"
        return self._result("success", summary, findings=findings, raw=data)


def _findings_from_lookup(data: dict[str, Any]) -> tuple[list[Finding], str | None]:
    findings: list[Finding] = []
    caller_name: str | None = None

    if data.get("phone_number"):
        findings.append(Finding(kind="phone", title="Twilio E.164", value=str(data["phone_number"])))
    if data.get("national_format"):
        findings.append(
            Finding(kind="metadata", title="National format", value=str(data["national_format"]))
        )
    if data.get("country_code"):
        findings.append(Finding(kind="metadata", title="Country", value=str(data["country_code"])))
    if data.get("valid") is False:
        findings.append(Finding(kind="note", title="Validity", value="Twilio marked this number invalid"))

    cnam = data.get("caller_name")
    if isinstance(cnam, dict):
        err = cnam.get("error_code")
        name = (cnam.get("caller_name") or "").strip() if cnam.get("caller_name") else ""
        ctype = (cnam.get("caller_type") or "").strip() if cnam.get("caller_type") else ""
        if name:
            caller_name = name
            findings.append(
                Finding(
                    kind="metadata",
                    title="Caller name (CNAM)",
                    value=name,
                    extra={"caller_type": ctype, "source": "twilio"},
                )
            )
            if ctype:
                findings.append(Finding(kind="metadata", title="Caller type", value=ctype))
        elif err:
            findings.append(
                Finding(
                    kind="note",
                    title="Caller name (CNAM)",
                    value=(
                        "Twilio CNAM add-on returned an error (often not enabled "
                        f"on this account): {err}"
                    ),
                )
            )
        else:
            findings.append(
                Finding(
                    kind="note",
                    title="Caller name (CNAM)",
                    value=EMPTY_CNAM_NOTE,
                )
            )
    elif cnam is None:
        findings.append(
            Finding(
                kind="note",
                title="Caller name (CNAM)",
                value=EMPTY_CNAM_NOTE,
            )
        )

    line = data.get("line_type_intelligence")
    if isinstance(line, dict):
        err = line.get("error_code")
        if line.get("carrier_name"):
            findings.append(
                Finding(kind="metadata", title="Carrier", value=str(line["carrier_name"]))
            )
        if line.get("type"):
            findings.append(
                Finding(kind="metadata", title="Line type", value=str(line["type"]))
            )
        if err and not (line.get("carrier_name") or line.get("type")):
            findings.append(
                Finding(
                    kind="note",
                    title="Line type intelligence",
                    value=f"Twilio line-type add-on error: {err}",
                )
            )

    return findings, caller_name
