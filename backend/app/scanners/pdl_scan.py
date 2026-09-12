from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner

# Official People Data Labs Person Enrichment (email → one person record).
# https://docs.peopledatalabs.com/docs/reference-person-enrichment-api
PDL_ENRICH_URL = "https://api.peopledatalabs.com/v5/person/enrich"

# Only these person-schema fields are requested. Emails, phones, birth dates,
# and street addresses are never asked for and never emitted.
_DATA_INCLUDE = ",".join(
    (
        "full_name",
        "job_title",
        "job_company_name",
        "location_name",
        "location_locality",
        "location_region",
        "location_country",
        "linkedin_url",
        "twitter_url",
        "facebook_url",
        "github_url",
        "profiles",
    )
)

_SOCIAL_FIELDS = (
    ("linkedin_url", "LinkedIn"),
    ("twitter_url", "Twitter"),
    ("facebook_url", "Facebook"),
    ("github_url", "GitHub"),
)

# Fields that must never appear as findings even if a response leaks them.
_BLOCKED_KEYS = {
    "birth_date",
    "birth_year",
    "email",
    "emails",
    "mobile_phone",
    "personal_emails",
    "phone_numbers",
    "phones",
    "possible_emails",
    "possible_phones",
    "recommended_personal_email",
    "street_address",
    "street_addresses",
}


def _api_key() -> str:
    return (os.getenv("PDL_API_KEY") or "").strip()


def _as_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _https_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    return text


def _is_person_profile_url(url: str) -> bool:
    if not is_concrete_profile_url(url):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    parts = [p for p in (parsed.path or "").split("/") if p]
    if host.endswith("linkedin.com") and parts and parts[0].lower() == "company":
        return False
    return True


def _location_label(person: dict[str, Any]) -> str:
    city = _as_text(person.get("location_locality"))
    region = _as_text(person.get("location_region"))
    if city and region:
        return f"{city}, {region}"
    if city:
        return city
    if region:
        return region
    name = _as_text(person.get("location_name"))
    if name:
        return name
    return _as_text(person.get("location_country"))


def _person_record(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("data")
    if isinstance(nested, dict):
        return nested
    if any(key in payload for key in ("full_name", "linkedin_url", "profiles", "job_title")):
        return payload
    return {}


def findings_from_person(person: dict[str, Any]) -> list[Finding]:
    """Public-safe fields only, and only when PDL actually returned them."""
    findings: list[Finding] = []
    seen_urls: set[str] = set()

    full_name = _as_text(person.get("full_name"))
    if full_name:
        findings.append(
            Finding(
                kind="note",
                title="Full name",
                value=full_name,
                extra={"source": "pdl"},
            )
        )

    job_title = _as_text(person.get("job_title"))
    if job_title:
        findings.append(
            Finding(
                kind="note",
                title="Job title",
                value=job_title,
                extra={"source": "pdl"},
            )
        )

    employer = _as_text(person.get("job_company_name"))
    if employer:
        findings.append(
            Finding(
                kind="note",
                title="Employer",
                value=employer,
                extra={"source": "pdl"},
            )
        )

    location = _location_label(person)
    if location:
        # Title avoids "location" / "region" so phone identity is not polluted.
        findings.append(
            Finding(
                kind="note",
                title="City / region",
                value=location,
                extra={"source": "pdl"},
            )
        )

    def _add_profile(title: str, raw_url: Any) -> None:
        href = _https_url(_as_text(raw_url))
        if not href or href in seen_urls or not _is_person_profile_url(href):
            return
        seen_urls.add(href)
        findings.append(
            Finding(
                kind="profile",
                title=title,
                value=href,
                url=href,
                extra={"source": "pdl"},
            )
        )

    for field, title in _SOCIAL_FIELDS:
        _add_profile(title, person.get(field))

    profiles = person.get("profiles")
    if isinstance(profiles, list):
        for row in profiles:
            if not isinstance(row, dict):
                continue
            network = _as_text(row.get("network")) or "profile"
            _add_profile(network.replace("_", " ").title(), row.get("url"))

    return findings


def public_fields(person: dict[str, Any]) -> dict[str, Any]:
    """Sanitized subset for raw/export — no email/phone/DOB/street dumps."""
    out: dict[str, Any] = {}
    for key in (
        "full_name",
        "job_title",
        "job_company_name",
        "location_name",
        "location_locality",
        "location_region",
        "location_country",
        "linkedin_url",
        "twitter_url",
        "facebook_url",
        "github_url",
    ):
        text = _as_text(person.get(key))
        if text:
            out[key] = text
    urls: list[dict[str, str]] = []
    profiles = person.get("profiles")
    if isinstance(profiles, list):
        for row in profiles:
            if not isinstance(row, dict):
                continue
            href = _https_url(_as_text(row.get("url")))
            if not href or not _is_person_profile_url(href):
                continue
            item: dict[str, str] = {"url": href}
            network = _as_text(row.get("network"))
            if network:
                item["network"] = network
            urls.append(item)
    if urls:
        out["profiles"] = urls
    return out


class PdlScanner(Scanner):
    id = "pdl"
    name = "People Data Labs"
    tool = "PDL Person Enrichment API"
    description = (
        "Optional. Email → People Data Labs Person Enrichment "
        f"({PDL_ENRICH_URL}) when PDL_API_KEY is set. Emits public-safe "
        "name, job, employer, city/region, and social profile URLs only when "
        "PDL returns them. No key → skipped, no fabricated person."
    )
    accepts = [QueryType.email]
    optional_key = "PDL_API_KEY"
    limitations = (
        "Requires PDL_API_KEY. Without it this module is skipped. v1 is email "
        "only (phone later). Never dumps emails, phones, birth dates, or street "
        "addresses. Empty fields stay empty — nothing is invented."
    )
    timeout = 15.0

    def available(self) -> bool:
        return bool(_api_key())

    async def run(self, query: Query) -> ScannerResult:
        key = _api_key()
        if not key:
            return self._result(
                "skipped",
                "PDL_API_KEY not set — optional module skipped",
            )
        email = (query.email or "").strip()
        if not email:
            return self._result("skipped", "No email")

        headers = {
            "X-Api-Key": key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        params = {
            "email": email,
            "pretty": "false",
            "titlecase": "true",
            "data_include": _DATA_INCLUDE,
        }
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                resp = await client.get(PDL_ENRICH_URL, params=params)
        except Exception as exc:
            return self._result("error", "PDL request failed", error=str(exc))

        payload: Any
        try:
            payload = resp.json() if resp.content else {}
        except Exception:
            payload = {}

        if resp.status_code == 404:
            return self._result(
                "success",
                "PDL has no person match for this email",
                findings=[],
                raw={"endpoint": PDL_ENRICH_URL, "status": 404},
            )
        if resp.status_code == 401:
            return self._result("error", "PDL rejected the API key", error="401 unauthorized")
        if resp.status_code == 402:
            return self._result("error", "PDL reports insufficient credits", error="402 payment required")
        if resp.status_code == 429:
            return self._result("error", "PDL rate-limited the request", error="429 too many requests")
        if resp.status_code != 200:
            message = ""
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict):
                    message = _as_text(err.get("message"))
                elif err:
                    message = str(err)
            return self._result(
                "error",
                f"PDL HTTP {resp.status_code}",
                error=message or f"HTTP {resp.status_code}",
            )

        person = _person_record(payload)
        for blocked in _BLOCKED_KEYS:
            person.pop(blocked, None)

        findings = findings_from_person(person)
        likelihood = payload.get("likelihood") if isinstance(payload, dict) else None
        raw = {
            "endpoint": PDL_ENRICH_URL,
            "status": 200,
            "likelihood": likelihood if isinstance(likelihood, int) else None,
            "public_fields": public_fields(person),
        }
        if findings:
            return self._result(
                "success",
                f"{len(findings)} public field(s) from PDL",
                findings=findings,
                raw=raw,
            )
        return self._result(
            "success",
            "PDL matched but returned no public-safe fields",
            findings=[],
            raw=raw,
        )
