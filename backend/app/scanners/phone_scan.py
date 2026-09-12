from __future__ import annotations

import asyncio
import importlib
import pkgutil
from typing import Any

import phonenumbers
from phonenumbers import carrier, geocoder, timezone
from phonenumbers.phonenumberutil import NumberParseException, number_type

from app.config import PHONE_TIMEOUT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner

LINE_TYPES = {
    0: "fixed line",
    1: "mobile",
    2: "fixed or mobile",
    3: "toll free",
    4: "premium rate",
    5: "shared cost",
    6: "VoIP",
    7: "personal number",
    8: "pager",
    9: "UAN",
    10: "unknown",
    27: "emergency",
    28: "voicemail",
    29: "short code",
    30: "standard rate",
}


class PhoneScanner(Scanner):
    id = "phone"
    name = "Phone metadata"
    tool = "phonenumbers + ignorant"
    description = (
        "Parses a number to E.164, country, carrier, time zone, and line type "
        "using Google libphonenumber data. If ignorant is installed, also checks "
        "whether the number appears registered on a few public sites."
    )
    accepts = [QueryType.phone]
    limitations = (
        "Carrier / region / line type come from the public libphonenumber dataset "
        "and can be stale. Site hits from ignorant mean the number is registered, "
        "not a profile URL. This is not a CNAM/caller-ID or address lookup unless "
        "you add Twilio Lookup keys. PhoneInfoga is not bundled as a binary."
    )
    timeout = PHONE_TIMEOUT

    def available(self) -> bool:
        return True

    async def run(self, query: Query) -> ScannerResult:
        raw_phone = query.phone_e164 or query.raw
        findings: list[Finding] = []
        meta: dict[str, Any] = {}
        try:
            parsed = phonenumbers.parse(raw_phone, "US")
        except NumberParseException as exc:
            return self._result("error", "Could not parse phone number", error=str(exc))

        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        intl = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
        valid = phonenumbers.is_valid_number(parsed)
        possible = phonenumbers.is_possible_number(parsed)
        region = geocoder.description_for_number(parsed, "en") or None
        region_code = phonenumbers.region_code_for_number(parsed)
        carr = carrier.name_for_number(parsed, "en") or None
        zones = list(timezone.time_zones_for_number(parsed) or [])
        ntype = LINE_TYPES.get(number_type(parsed), "unknown")

        meta = {
            "e164": e164,
            "international": intl,
            "valid": valid,
            "possible": possible,
            "region": region,
            "region_code": region_code,
            "carrier": carr,
            "timezones": zones,
            "line_type": ntype,
            "country_code": parsed.country_code,
            "national_number": parsed.national_number,
        }
        findings.append(
            Finding(
                kind="phone",
                title="E.164",
                value=e164,
                extra=meta,
            )
        )
        findings.append(Finding(kind="metadata", title="Formatted", value=intl))
        findings.append(
            Finding(
                kind="metadata",
                title="Validity",
                value="valid libphonenumber match" if valid else "possible but not a confirmed valid number",
            )
        )
        if region:
            findings.append(Finding(kind="metadata", title="Region", value=region))
        if region_code:
            findings.append(Finding(kind="metadata", title="Country", value=region_code))
        if carr:
            findings.append(Finding(kind="metadata", title="Carrier (dataset)", value=carr))
        findings.append(Finding(kind="metadata", title="Line type", value=ntype))
        if zones:
            findings.append(
                Finding(kind="metadata", title="Time zones", value=", ".join(zones))
            )

        ignorant_raw = await asyncio.to_thread(
            self._ignorant,
            str(parsed.national_number),
            str(parsed.country_code),
        )
        if ignorant_raw.get("unavailable"):
            findings.append(
                Finding(
                    kind="note",
                    title="Site checks",
                    value="ignorant not installed — metadata only",
                )
            )
        else:
            for row in ignorant_raw.get("exists", []):
                domain = row.get("domain") or row.get("name")
                raw_url = row.get("url") or row.get("link")
                if not raw_url and domain:
                    raw_url = f"https://{domain}"
                # Registration ≠ profile. Never link a bare site homepage.
                if is_concrete_profile_url(raw_url if isinstance(raw_url, str) else None):
                    findings.append(
                        Finding(
                            kind="profile",
                            title=str(row.get("name") or domain),
                            value=f"Number associated on {domain}",
                            url=str(raw_url),
                            extra=row,
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            kind="note",
                            title=str(row.get("name") or domain or "Site registration"),
                            value=f"Number appears registered on {domain} (not a profile URL)",
                            extra=row,
                        )
                    )
            if not ignorant_raw.get("exists"):
                findings.append(
                    Finding(
                        kind="note",
                        title="Site checks",
                        value=f"ignorant checked {ignorant_raw.get('checked', 0)} site(s); none claimed this number",
                    )
                )

        summary = f"{e164} · {ntype}" + (f" · {carr}" if carr else "")
        return self._result("success", summary, findings=findings, raw={"meta": meta, "ignorant": ignorant_raw})

    def _ignorant(self, national: str, country_code: str) -> dict[str, Any]:
        try:
            import ignorant.modules as modules
            import httpx
            import trio
        except Exception:
            return {"unavailable": True}

        functions: list[Any] = []

        def walk(package: Any) -> None:
            for _loader, name, is_pkg in pkgutil.walk_packages(package.__path__):
                full = package.__name__ + "." + name
                try:
                    mod = importlib.import_module(full)
                except Exception:
                    continue
                if is_pkg:
                    walk(mod)
                    continue
                fn = getattr(mod, full.split(".")[-1], None)
                if callable(fn):
                    functions.append(fn)

        walk(modules)
        if not functions:
            return {"unavailable": True, "reason": "no modules"}

        async def _scan() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            client = httpx.AsyncClient(timeout=8.0)
            try:
                async with trio.open_nursery() as nursery:
                    for fn in functions:

                        async def _one(func=fn) -> None:
                            try:
                                await func(national, country_code, client, out)
                            except Exception:
                                return

                        nursery.start_soon(_one)
            finally:
                await client.aclose()
            return out

        try:
            raw = trio.run(_scan)
        except Exception as exc:
            return {"error": str(exc), "exists": [], "checked": 0}

        exists = [r for r in raw if r.get("exists") and not r.get("rateLimit")]
        return {"checked": len(raw), "exists": exists, "all": raw}
