from __future__ import annotations

import os
from datetime import datetime
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

# Pass through only keys Trestle actually returned. Do not invent siblings.
_ADDRESS_FIELD_KEYS = (
    "id",
    "location_type",
    "street_line_1",
    "street_line_2",
    "city",
    "postal_code",
    "zip4",
    "state_code",
    "country_code",
    "lat_long",
    "accuracy",
    "delivery_point",
    "link_to_person_start_date",
)

_OWNER_FIELD_KEYS = (
    "id",
    "name",
    "firstname",
    "middlename",
    "lastname",
    "alternate_names",
    "age_range",
    "gender",
    "type",
    "link_to_phone_start_date",
    "industry",
)

_ADDRESS_LIST_KEYS = (
    "current_addresses",
    "historical_addresses",
    "associated_addresses",
    "addresses",
)


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


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        return any(_is_present(v) for v in value.values())
    if isinstance(value, list):
        return any(_is_present(v) for v in value)
    return True


def _present_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        cleaned = {k: _present_value(v) for k, v in value.items() if _is_present(v)}
        return cleaned
    if isinstance(value, list):
        return [_present_value(v) for v in value if _is_present(v)]
    return value


def _present_fields(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if not _is_present(value):
            continue
        out[key] = _present_value(value)
    return out


def parse_link_date(value: Any) -> datetime | None:
    """Parse Trestle ISO / date-only link dates. Empty or junk → None."""
    text = _as_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def pick_current_address(addresses: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Newest link_to_person_start_date wins. Null dates rank older than any dated row."""
    if not addresses:
        return None

    def _key(item: tuple[int, dict[str, Any]]) -> tuple[bool, datetime, int]:
        index, row = item
        parsed = parse_link_date(row.get("link_to_person_start_date"))
        return (parsed is not None, parsed or datetime.min, -index)

    return max(enumerate(addresses), key=_key)[1]


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


def collect_owner_addresses(owner: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in _ADDRESS_LIST_KEYS:
        raw = owner.get(key)
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
            if not label:
                continue
            dedupe = label.lower()
            if dedupe in seen:
                continue
            seen.add(dedupe)
            rows.append(item)
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
    seen: set[tuple[Any, ...]] = set()

    def _add(
        kind: Literal["email", "note", "metadata"],
        title: str,
        value: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        text = value.strip()
        if not text:
            return
        owner_idx = extra.get("owner_index") if extra else None
        key = (kind, title, text.lower(), owner_idx)
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

    for owner_index, owner in enumerate(_owners(payload)):
        name = _owner_name(owner)
        owner_fields = _present_fields(owner, _OWNER_FIELD_KEYS)
        addresses = collect_owner_addresses(owner)
        current = pick_current_address(addresses)

        if name:
            extra: dict[str, Any] = {
                "finding_type": "trestle_owner",
                "owner_index": owner_index,
                "owner": owner_fields,
            }
            owner_type = _as_text(owner.get("type"))
            if owner_type:
                extra["owner_type"] = owner_type
            _add("note", "Name", name, extra)

        for alt in owner.get("alternate_names") or []:
            alt_name = _as_text(alt)
            if alt_name and alt_name.lower() != name.lower():
                _add(
                    "note",
                    "Alternate name",
                    alt_name,
                    {
                        "finding_type": "trestle_owner_field",
                        "owner_index": owner_index,
                    },
                )

        for row in addresses:
            formatted = _format_address(row)
            fields = _present_fields(row, _ADDRESS_FIELD_KEYS)
            is_current = row is current
            extra = {
                "finding_type": "trestle_address",
                "owner_index": owner_index,
                "is_current": is_current,
                "fields": fields,
            }
            if name:
                extra["owner_name"] = name
            for old_key, src_key in (
                ("street", "street_line_1"),
                ("city", "city"),
                ("state", "state_code"),
                ("zip", "postal_code"),
            ):
                text = _as_text(row.get(src_key))
                if text:
                    extra[old_key] = text
            title = "Current address" if is_current else "Address"
            _add("note", title, formatted, extra)

        for email in _emails_from(owner):
            _add(
                "email",
                "Email",
                email,
                {"finding_type": "trestle_owner_field", "owner_index": owner_index},
            )

    return findings


def owners_blob_from_findings(findings: list[Finding]) -> list[dict[str, Any]]:
    """Compact owner/address JSON for export — only fields already on findings."""
    owners: dict[int, dict[str, Any]] = {}
    order: list[int] = []

    def _bucket(index: int) -> dict[str, Any]:
        if index not in owners:
            owners[index] = {"owner_index": index, "addresses": []}
            order.append(index)
        return owners[index]

    for finding in findings:
        extra = finding.extra or {}
        if extra.get("source") != "trestle":
            continue
        raw_index = extra.get("owner_index")
        if not isinstance(raw_index, int):
            continue
        bucket = _bucket(raw_index)
        ftype = extra.get("finding_type")
        if ftype == "trestle_owner":
            if finding.value:
                bucket["name"] = finding.value
            owner = extra.get("owner")
            if isinstance(owner, dict) and owner:
                bucket["fields"] = owner
        elif ftype == "trestle_address":
            fields = extra.get("fields") if isinstance(extra.get("fields"), dict) else {}
            bucket["addresses"].append(
                {
                    "formatted": finding.value,
                    "is_current": bool(extra.get("is_current")),
                    "fields": fields,
                }
            )
    return [owners[i] for i in order]


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
        "Emits owner names and returned demographics, current/associated "
        "addresses with Trestle address fields, emails, and brief line "
        "metadata only when Trestle returns them. E.164 preferred. "
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
            "owners": owners_blob_from_findings(findings),
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
