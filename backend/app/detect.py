from __future__ import annotations

import os
import re
import unicodedata

import phonenumbers
from phonenumbers import NumberParseException

from app.config import SOCIAL_USERNAME_CANDIDATES
from app.models import Finding, Query, QueryType

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)
# Loose international / NANP: +1 415 555 2671, (415) 555-2671, 00 33 6...
PHONE_HINT_RE = re.compile(
    r"^[\s]*(\+|00)?[\s\-\(\).]*\d[\d\s\-\(\).]{6,20}$"
)
USERNAME_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9._\-]{1,31}$")
NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]+(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]+){1,4}$")


def _norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def detect_type(raw: str) -> QueryType:
    text = _norm(raw)
    if EMAIL_RE.match(text):
        return QueryType.email
    if _looks_like_phone(text):
        return QueryType.phone
    if NAME_RE.match(text):
        return QueryType.name
    if USERNAME_RE.match(text.lstrip("@")):
        return QueryType.username
    if " " in text:
        return QueryType.name
    return QueryType.username


def _looks_like_phone(text: str) -> bool:
    if not PHONE_HINT_RE.match(text):
        return False
    digits = re.sub(r"\D", "", text)
    if len(digits) < 8 or len(digits) > 15:
        return False
    try:
        parsed = phonenumbers.parse(text, "US")
        return phonenumbers.is_possible_number(parsed)
    except NumberParseException:
        try:
            parsed = phonenumbers.parse("+" + digits, None)
            return phonenumbers.is_possible_number(parsed)
        except NumberParseException:
            return False


def parse_phone(text: str) -> tuple[str | None, str | None, str | None]:
    candidates = [text]
    digits = re.sub(r"\D", "", text)
    if text.startswith("00") and len(digits) >= 8:
        candidates.append("+" + digits)
    for candidate in candidates:
        for region in (None, "US"):
            try:
                parsed = phonenumbers.parse(candidate, region)
            except NumberParseException:
                continue
            if not phonenumbers.is_possible_number(parsed):
                continue
            e164 = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
            national = str(parsed.national_number)
            cc = str(parsed.country_code)
            return e164, national, cc
    return None, None, None


def _clean_handle(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9._\-]", "", value)
    cleaned = cleaned.strip("._-")
    if 2 <= len(cleaned) <= 32:
        return cleaned
    return None


def username_candidates(query: Query) -> list[str]:
    found: list[str] = []

    def add(value: str | None) -> None:
        cleaned = _clean_handle(value)
        if cleaned and cleaned.lower() not in {x.lower() for x in found}:
            found.append(cleaned)

    if query.email:
        local = query.email.split("@", 1)[0]
        plus_base = local.split("+", 1)[0]
        compact = re.sub(r"[.+]", "", local)
        # Dotted / plus-tagged Gmail locals are rejected by most social sites.
        # Put the alphanumeric variant first so Sherlock/Maigret try it.
        if "." in local or "+" in local:
            add(compact)
            if plus_base != local:
                add(plus_base.replace(".", ""))
                add(plus_base)
            add(local)
        else:
            add(local)
        add(local.replace("_", ""))
        # Do not strip trailing digits (stpayne55 → stpayne). Those guesses
        # hit unrelated social accounts. Undotted / plus-stripped locals stay.
    if query.username:
        handle = query.username.lstrip("@")
        add(handle)
        if "." in handle or "+" in handle:
            add(re.sub(r"[.+]", "", handle))
    if query.name:
        parts = [p for p in re.split(r"\s+", query.name) if p]
        if parts:
            first = re.sub(r"[^A-Za-z]", "", parts[0])
            last = re.sub(r"[^A-Za-z]", "", parts[-1]) if len(parts) > 1 else ""
            add("".join(parts))
            if first and last:
                add(first + last)
                add(first + "." + last)
                add(first + "_" + last)
                add(first[0] + last)
                add(first + last[0])
                add(last + first)
                add(first + "." + last[0])
    return found[:12]


def social_candidate_limit(limit: int | None = None) -> int:
    if limit is not None:
        return max(1, min(3, limit))
    return max(1, min(3, _int_social_cap()))


def _int_social_cap() -> int:
    raw = (os.getenv("SOCIAL_USERNAME_CANDIDATES") or "").strip()
    if raw:
        try:
            return max(1, min(3, int(raw)))
        except ValueError:
            pass
    return max(1, min(3, SOCIAL_USERNAME_CANDIDATES))


def social_username_candidates(query: Query, limit: int | None = None) -> list[str]:
    """Handles Sherlock / Maigret / Socialscan should actually query.

    Builds an ordered list from ``username_candidates`` plus the primary
    username, prefers undotted / alphanumeric handles when the email
    local-part contains ``.`` or ``+``, and caps at 2–3
    (``SOCIAL_USERNAME_CANDIDATES``, default 2).
    """
    cap = social_candidate_limit(limit)
    seen: set[str] = set()
    ordered: list[str] = []

    def add(value: str | None) -> None:
        cleaned = _clean_handle(value.lstrip("@") if value else None)
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        ordered.append(cleaned)

    for candidate in query.username_candidates:
        add(candidate)
    add(query.username)
    if query.email:
        add(query.email.split("@", 1)[0])

    email_local = (query.email or "").split("@", 1)[0]
    if email_local and ("." in email_local or "+" in email_local):

        def rank(handle: str) -> tuple[int, int]:
            seps = 1 if any(ch in handle for ch in ".+") else 0
            non_alnum = 1 if re.search(r"[^A-Za-z0-9]", handle) else 0
            return (seps, non_alnum)

        # Stable sort: keep detect order, just float site-friendly handles first.
        ordered.sort(key=rank)

    return ordered[:cap]


def merge_findings_by_url(findings: list[Finding]) -> list[Finding]:
    """Keep first finding per concrete URL (or kind/title/value when URL-less)."""
    seen: set[str] = set()
    merged: list[Finding] = []
    for finding in findings:
        if finding.url:
            key = "url:" + finding.url.rstrip("/").lower()
        else:
            key = f"{finding.kind}|{finding.title}|{finding.value}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(finding)
    return merged


def format_tried_handles(handles: list[str]) -> str:
    return ", ".join(f"@{h}" for h in handles)


def derive_username(query: Query) -> str | None:
    """Primary handle for social search (first social candidate)."""
    handles = social_username_candidates(query, limit=1)
    return handles[0] if handles else None


def build_query(raw: str, override: QueryType = QueryType.auto) -> Query:
    text = _norm(raw)
    if not text:
        raise ValueError("Query is empty")
    qtype = override if override != QueryType.auto else detect_type(text)
    query = Query(raw=text, type=qtype)

    if qtype == QueryType.email:
        query.email = text.lower()
        query.domain = text.split("@", 1)[1].lower()
        query.username = text.split("@", 1)[0].lower()
    elif qtype == QueryType.phone:
        e164, national, cc = parse_phone(text)
        query.phone_e164 = e164
        query.phone_national = national
        query.phone_country_code = cc
    elif qtype == QueryType.name:
        query.name = " ".join(text.split())
    else:
        query.username = text.lstrip("@")

    query.username_candidates = username_candidates(query)
    if query.username_candidates and not query.username:
        query.username = query.username_candidates[0]
    return query
