from __future__ import annotations

import os
from typing import Any, Literal

import httpx
import phonenumbers
from phonenumbers import NumberParseException

from app.config import USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner

# Official Trestle Reverse Phone API 3.2.
# https://docs.trestleiq.com/api-reference/reverse-phone-api
# GET https://api.trestleiq.com/3.2/phone?phone=…  header: x-api-key
TRESTLE_REVERSE_PHONE_URL = "https://api.trestleiq.com/3.2/phone"

_SOURCE = {"source": "trestle"}


def _api_key() -> str:
    return (os.getenv("TRESTLE_API_KEY") or "").strip()


def _as_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _phone_query(query: Query) -> str:
    """E.164 preferred; fall back to national / raw phone only."""
    if query.phone_e164:
        return query.phone_e164.strip()
    if query.phone_national:
        return query.phone_national.strip()
    if query.type == QueryType.phone:
        return (query.raw or "").strip()
    return ""


def _country_hint(number: str) -> str:
    try:
        parsed = phonenumbers.parse(number, None if number.startswith("+") else "US")
    except NumberParseException:
        return ""
    return phonenumbers.region_code_for_number(parsed) or ""


def _owners(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("owners", "belongs_to"):
        raw = payload.get(key)
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        if isinstance(raw, dict):
            return [raw]
    return []


def _owner_name(owner: dict[str, Any]) -> str:
    name = _as_text(owner.get("name"))
    if name:
        return name
    parts = [
        _as_text(owner.get("firstname")),
        _as_text(owner.get("middlename")),
        _as_text(owner.get("lastname")),
    ]
    return " ".join(p for p in parts if p)


def _format_address(row: dict[str, Any]) -> str:
    street = " ".join(
        p for p in (_as_text(row.get("street_line_1")), _as_text(row.get("street_line_2"))) if p
    )
    city = _as_text(row.get("city"))
    state = _as_text(row.get("state_code"))
    postal = _as_text(row.get("postal_code") or row.get("zip4"))
    country = _as_text(row.get("country_code"))
    locality = ", ".join(p for p in (city, state) if p)
    if locality and postal:
        locality = f"{locality} {postal}"
    elif postal:
        locality = postal
    chunks = [p for p in (street, locality) if p]
    if country and country.upper() not in {"US", "USA"}:
        chunks.append(country)
    return ", ".join(chunks)


def _address_rows(owner: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    mapping = (
        ("current_addresses", "Current address"),
        ("historical_addresses", "Historical address"),
        ("associated_addresses", "Associated address"),
        ("addresses", "Address"),
    )
    rows: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for key, title in mapping:
        raw = owner.get(key)
        items: list[Any]
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = [raw]
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            label = _format_address(item)
            if not label or label in seen:
                continue
            seen.add(label)
            rows.append((title, item))
    return rows


def _emails_from(owner: dict[str, Any]) -> list[str]:
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

    _add(owner.get("email"))
    for key in ("emails", "email_addresses"):
        raw = owner.get(key)
        if isinstance(raw, str):
            _add(raw)
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    _add(item)
                elif isinstance(item, dict):
                    _add(item.get("address") or item.get("email"))
    return found


def findings_from_reverse_phone(payload: dict[str, Any]) -> list[Finding]:
    """Emit only fields Trestle actually returned. Never invent a name or address."""
    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(
        kind: Literal["email", "note", "metadata"],
        title: str,
        value: str,
        extra: dict[str, Any] | None = None,
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
        findings.append(Finding(kind=kind, title=title, value=text, extra=payload_extra))

    if payload.get("is_valid") is False:
        _add("note", "Validity", "Trestle marked this number invalid")

    line_type = _as_text(payload.get("line_type"))
    if line_type:
        _add("metadata", "Line type", line_type)
    carrier = _as_text(payload.get("carrier"))
    if carrier:
        _add("metadata", "Carrier", carrier)
    if payload.get("is_prepaid") is True:
        _add("metadata", "Prepaid", "prepaid")
    if payload.get("is_commercial") is True:
        _add("metadata", "Commercial", "commercial line")

    for owner in _owners(payload):
        name = _owner_name(owner)
        if name:
            extra: dict[str, Any] = {}
            owner_type = _as_text(owner.get("type"))
            if owner_type:
                extra["owner_type"] = owner_type
            _add("note", "Name", name, extra)

        for alt in owner.get("alternate_names") or []:
            alt_name = _as_text(alt)
            if alt_name and alt_name.lower() != name.lower():
                _add("note", "Alternate name", alt_name)

        for title, row in _address_rows(owner):
            formatted = _format_address(row)
            extra = {
                k: v
                for k, v in {
                    "street": _as_text(row.get("street_line_1")),
                    "city": _as_text(row.get("city")),
                    "state": _as_text(row.get("state_code")),
                    "zip": _as_text(row.get("postal_code")),
                }.items()
                if v
            }
            _add("note", title, formatted, extra)

        for email in _emails_from(owner):
            _add("email", "Email", email)

    return findings


def _error_message(payload: Any, status_code: int) -> str:
    if not isinstance(payload, dict):
        return f"HTTP {status_code}"
    for key in ("message", "errorCode", "error"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, dict):
            nested = _as_text(raw.get("message") or raw.get("name"))
            if nested:
                return nested
    return f"HTTP {status_code}"


class TrestleReversePhoneScanner(Scanner):
    id = "trestle"
    name = "Trestle Reverse Phone"
    tool = "Trestle Reverse Phone API"
    description = (
        "Optional. Phone → Trestle Reverse Phone "
        f"({TRESTLE_REVERSE_PHONE_URL}?phone=) when TRESTLE_API_KEY is set. "
        "Emits owner names, current/associated addresses, emails, and brief "
        "line metadata only when Trestle returns them. E.164 preferred. "
        "No key → skipped, no HTTP."
    )
    accepts = [QueryType.phone]
    optional_key = "TRESTLE_API_KEY"
    limitations = (
        "Requires TRESTLE_API_KEY. Without it this module is skipped. "
        "Phone queries only. Official API — documented x-api-key header. "
        "Missing fields stay empty — nothing is invented. Does not scrape "
        "Whitepages/Spokeo and does not return breach data."
    )
    timeout = 15.0

    def available(self) -> bool:
        return bool(_api_key())

    async def run(self, query: Query) -> ScannerResult:
        key = _api_key()
        if not key:
            return self._result(
                "skipped",
                "TRESTLE_API_KEY not set — optional module skipped",
            )
        number = _phone_query(query)
        if not number:
            return self._result("skipped", "No phone")

        headers = {
            "x-api-key": key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        params: dict[str, str] = {"phone": number}
        hint = _country_hint(number)
        if hint:
            params["phone.country_hint"] = hint

        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                resp = await client.get(TRESTLE_REVERSE_PHONE_URL, params=params)
        except Exception as exc:
            return self._result("error", "Trestle request failed", error=str(exc))

        payload: Any
        try:
            payload = resp.json() if resp.content else {}
        except Exception:
            payload = {}

        if resp.status_code == 404:
            return self._result(
                "success",
                "Trestle has no reverse-phone match",
                findings=[],
                raw={"endpoint": TRESTLE_REVERSE_PHONE_URL, "status": 404},
            )
        if resp.status_code == 403:
            return self._result(
                "error",
                "Trestle rejected the API key",
                error=_error_message(payload, 403),
            )
        if resp.status_code == 401:
            return self._result("error", "Trestle rejected the API key", error="401 unauthorized")
        if resp.status_code == 429:
            return self._result("error", "Trestle rate-limited the request", error="429 too many requests")
        if resp.status_code != 200:
            return self._result(
                "error",
                f"Trestle HTTP {resp.status_code}",
                error=_error_message(payload, resp.status_code),
            )

        data = payload if isinstance(payload, dict) else {}
        findings = findings_from_reverse_phone(data)
        raw = {
            "endpoint": TRESTLE_REVERSE_PHONE_URL,
            "status": 200,
            "phone_number": _as_text(data.get("phone_number")) or None,
            "is_valid": data.get("is_valid") if isinstance(data.get("is_valid"), bool) else None,
            "finding_count": len(findings),
        }
        if findings:
            names = [f.value for f in findings if f.title == "Name"]
            summary = (
                f"Owner: {names[0]}" if names else f"{len(findings)} field(s) from Trestle"
            )
            return self._result("success", summary, findings=findings, raw=raw)
        return self._result(
            "success",
            "Trestle returned no name, address, or email fields",
            findings=[],
            raw=raw,
        )
