from __future__ import annotations

import re
import unicodedata

import phonenumbers
from phonenumbers import NumberParseException

from app.models import Query, QueryType

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


def username_candidates(query: Query) -> list[str]:
    found: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        cleaned = re.sub(r"[^A-Za-z0-9._\-]", "", value)
        cleaned = cleaned.strip("._-")
        if 2 <= len(cleaned) <= 32 and cleaned.lower() not in {x.lower() for x in found}:
            found.append(cleaned)

    if query.username:
        add(query.username.lstrip("@"))
    if query.email:
        local = query.email.split("@", 1)[0]
        add(local)
        add(local.replace(".", ""))
        add(local.replace("_", ""))
        add(re.sub(r"\d+$", "", local))
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


def build_query(raw: str, override: QueryType = QueryType.auto) -> Query:
    text = _norm(raw)
    if not text:
        raise ValueError("Query is empty")
    qtype = override if override != QueryType.auto else detect_type(text)
    query = Query(raw=text, type=qtype)

    if qtype == QueryType.email:
        query.email = text.lower()
        query.domain = text.split("@", 1)[1].lower()
        query.username = text.split("@", 1)[0]
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
