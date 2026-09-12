from __future__ import annotations

import os
from typing import Any, Literal

import httpx

from app.config import USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner

# Official Whitepages Pro Person Search — reverse phone via `phone=`.
# https://api.whitepages.com/docs/documentation/person-search/reverse-phone-lookup
# Auth: X-Api-Key header — https://api.whitepages.com/docs/references/authentication
WHITEPAGES_PERSON_URL = "https://api.whitepages.com/v2/person"

_SOURCE = {"source": "whitepages"}
_MAX_PEOPLE = 5
_MAX_RELATIVES = 5


def _api_key() -> str:
    return (os.getenv("WHITEPAGES_API_KEY") or "").strip()


def _as_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _phone_query(query: Query) -> str:
    if query.phone_e164:
        return query.phone_e164.strip()
    if query.phone_national:
        return query.phone_national.strip()
    if query.type == QueryType.phone:
        return (query.raw or "").strip()
    return ""


def _people(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if isinstance(results, list):
        return [row for row in results if isinstance(row, dict)]
    if any(key in payload for key in ("name", "current_addresses", "phones", "id")):
        return [payload]
    return []


def _format_address(row: Any) -> str:
    if isinstance(row, str):
        return row.strip()
    if not isinstance(row, dict):
        return ""
    full = _as_text(row.get("full_address") or row.get("address"))
    if full:
        return full
    street = _as_text(row.get("line1") or row.get("street_line_1") or row.get("street"))
    city = _as_text(row.get("city"))
    state = _as_text(row.get("state") or row.get("state_code"))
    postal = _as_text(row.get("zip") or row.get("zipcode") or row.get("postal_code"))
    locality = ", ".join(p for p in (city, state) if p)
    if locality and postal:
        locality = f"{locality} {postal}"
    elif postal:
        locality = postal
    return ", ".join(p for p in (street, locality) if p)


def _address_rows(person: dict[str, Any]) -> list[tuple[str, str]]:
    mapping = (
        ("current_addresses", "Current address"),
        ("historic_addresses", "Historical address"),
        ("historical_addresses", "Historical address"),
        ("owned_properties", "Associated address"),
    )
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, title in mapping:
        raw = person.get(key)
        items: list[Any]
        if isinstance(raw, list):
            items = raw
        elif raw:
            items = [raw]
        else:
            items = []
        for item in items:
            label = _format_address(item)
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            rows.append((title, label))
    return rows


def _emails_from(person: dict[str, Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def _add(value: Any) -> None:
        text = _as_text(value)
        if "@" not in text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(text)

    _add(person.get("email"))
    raw = person.get("emails")
    if isinstance(raw, str):
        _add(raw)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                _add(item)
            elif isinstance(item, dict):
                _add(item.get("email") or item.get("address"))
    return found


def findings_from_people(payload: Any) -> list[Finding]:
    """Emit only fields Whitepages actually returned. Never invent a name or address."""
    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(
        kind: Literal["email", "note", "metadata", "profile"],
        title: str,
        value: str,
        extra: dict[str, Any] | None = None,
        url: str | None = None,
    ) -> None:
        text = value.strip()
        if not text:
            return
        key = (kind, title, text.lower())
        if key in seen:
            return
        seen.add(key)
        payload_extra = dict(_SOURCE)
        if extra:
            payload_extra.update(extra)
        findings.append(
            Finding(kind=kind, title=title, value=text, url=url, extra=payload_extra)
        )

    for person in _people(payload)[:_MAX_PEOPLE]:
        name = _as_text(person.get("name"))
        if name:
            _add("note", "Name", name)

        for alias in person.get("aliases") or []:
            alt = _as_text(alias)
            if alt and alt.lower() != name.lower():
                _add("note", "Alternate name", alt)

        job = _as_text(person.get("job_title"))
        if job:
            _add("note", "Job title", job)
        company = _as_text(person.get("company_name"))
        if company:
            _add("note", "Employer", company)

        linkedin = _as_text(person.get("linkedin_url"))
        if linkedin and is_concrete_profile_url(linkedin):
            _add("profile", "LinkedIn", linkedin, url=linkedin)

        for title, address in _address_rows(person):
            _add("note", title, address)

        for email in _emails_from(person):
            _add("email", "Email", email)

        phones = person.get("phones")
        if isinstance(phones, list):
            for row in phones:
                if not isinstance(row, dict):
                    continue
                line_type = _as_text(row.get("type"))
                if line_type:
                    _add("metadata", "Line type", line_type)
                    break

        relatives = person.get("relatives")
        if isinstance(relatives, list):
            for rel in relatives[:_MAX_RELATIVES]:
                rel_name = _as_text(rel.get("name") if isinstance(rel, dict) else rel)
                if rel_name and rel_name.lower() != name.lower():
                    _add("note", "Relative", rel_name)

    return findings


def _error_message(payload: Any, status_code: int) -> str:
    if not isinstance(payload, dict):
        return f"HTTP {status_code}"
    err = payload.get("error")
    if isinstance(err, dict):
        for key in ("long_message", "message"):
            text = _as_text(err.get(key))
            if text:
                return text
    for key in ("message", "error"):
        text = _as_text(payload.get(key))
        if text:
            return text
    return f"HTTP {status_code}"


class WhitepagesProScanner(Scanner):
    id = "whitepages"
    name = "Whitepages Pro"
    tool = "Whitepages Pro Person Search API"
    description = (
        "Optional. Phone → Whitepages Pro Person Search "
        f"({WHITEPAGES_PERSON_URL}?phone=) when WHITEPAGES_API_KEY is set. "
        "Emits owner names, current/historical addresses, emails, and other "
        "returned public fields only when Whitepages returns them. No key → "
        "skipped, no HTTP. Does not scrape whitepages.com."
    )
    accepts = [QueryType.phone]
    optional_key = "WHITEPAGES_API_KEY"
    limitations = (
        "Requires WHITEPAGES_API_KEY. Without it this module is skipped. "
        "Phone queries only. Official API — not a Whitepages.com scrape. "
        "Missing fields stay empty — nothing is invented. No breach data."
    )
    timeout = 15.0

    def available(self) -> bool:
        return bool(_api_key())

    async def run(self, query: Query) -> ScannerResult:
        key = _api_key()
        if not key:
            return self._result(
                "skipped",
                "WHITEPAGES_API_KEY not set — optional module skipped",
            )
        number = _phone_query(query)
        if not number:
            return self._result("skipped", "No phone")

        headers = {
            "X-Api-Key": key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        params = {"phone": number}
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                resp = await client.get(WHITEPAGES_PERSON_URL, params=params)
        except Exception as exc:
            return self._result("error", "Whitepages Pro request failed", error=str(exc))

        payload: Any
        try:
            payload = resp.json() if resp.content else {}
        except Exception:
            payload = {}

        if resp.status_code == 404:
            return self._result(
                "success",
                "Whitepages Pro has no reverse-phone match",
                findings=[],
                raw={"endpoint": WHITEPAGES_PERSON_URL, "status": 404},
            )
        if resp.status_code == 403:
            return self._result(
                "error",
                "Whitepages Pro rejected the API key",
                error=_error_message(payload, 403),
            )
        if resp.status_code == 401:
            return self._result(
                "error",
                "Whitepages Pro rejected the API key",
                error="401 unauthorized",
            )
        if resp.status_code == 429:
            return self._result(
                "error",
                "Whitepages Pro rate-limited the request",
                error="429 too many requests",
            )
        if resp.status_code != 200:
            return self._result(
                "error",
                f"Whitepages Pro HTTP {resp.status_code}",
                error=_error_message(payload, resp.status_code),
            )

        findings = findings_from_people(payload)
        raw = {
            "endpoint": WHITEPAGES_PERSON_URL,
            "status": 200,
            "result_count": len(_people(payload)),
            "finding_count": len(findings),
        }
        if findings:
            names = [f.value for f in findings if f.title == "Name"]
            summary = (
                f"Owner: {names[0]}" if names else f"{len(findings)} field(s) from Whitepages Pro"
            )
            return self._result("success", summary, findings=findings, raw=raw)
        return self._result(
            "success",
            "Whitepages Pro returned no name, address, or email fields",
            findings=[],
            raw=raw,
        )
