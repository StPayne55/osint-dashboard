from __future__ import annotations

import re
from urllib.parse import quote_plus

import phonenumbers
from phonenumbers import NumberParseException

from app.models import Finding, Query, QueryType


def _g(q: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(q)}"


def _ddg(q: str) -> str:
    return f"https://duckduckgo.com/?q={quote_plus(q)}"


def _bing(q: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(q)}"


def build_dorks(query: Query) -> list[Finding]:
    links: list[Finding] = []

    def add(title: str, q: str, engine: str = "google") -> None:
        url = {"google": _g, "ddg": _ddg, "bing": _bing}[engine](q)
        links.append(
            Finding(
                kind="link",
                title=title,
                value=q,
                url=url,
                extra={"engine": engine},
            )
        )

    raw = query.raw
    if query.type == QueryType.email and query.email:
        email = query.email
        domain = query.domain or email.split("@", 1)[1]
        add("Google — exact email", f'"{email}"')
        add("DuckDuckGo — exact email", f'"{email}"', "ddg")
        add("Bing — exact email", f'"{email}"', "bing")
        add("Google — email + profile", f'"{email}" (profile OR bio OR about)')
        add("Google — email filetype leaks", f'"{email}" (filetype:pdf OR filetype:xlsx OR filetype:csv)')
        add("Google — site:linkedin", f'site:linkedin.com/in "{email}" OR "{query.username}"')
        add("Google — GitHub", f'site:github.com "{email}"')
        add("Google — Gravatar / WordPress", f'site:gravatar.com OR site:wordpress.com "{email}"')
        add("Hunter-style domain staff pages", f'site:{domain} ("email" OR contact) "{query.username}"')
        add("Have I Been Pwned (manual)", email)
        links[-1].url = f"https://haveibeenpwned.com/account/{quote_plus(email)}"
        add("Epieos email OSINT (manual)", email)
        links[-1].url = f"https://epieos.com/?q={quote_plus(email)}"
    elif query.type == QueryType.phone and (query.phone_e164 or raw):
        variants = _phone_text_variants(query)
        phone = variants["e164"] or query.phone_e164 or raw
        dashed = variants["dashed"]
        dotted = variants["dotted"]
        national = variants["national"]
        paren = variants["paren"]
        intl = variants["international"]

        add("Google — exact E.164", f'"{phone}"')
        if national and national != phone:
            add("Google — national digits", f'"{national}"')
        if dashed and dashed not in {phone, national}:
            add("Google — dashed format", f'"{dashed}"')
        add("DuckDuckGo — phone", f'"{phone}"', "ddg")
        add("Bing — phone", f'"{phone}"', "bing")
        add(
            "Google — OpenCNAM / caller-ID style (manual)",
            f'"{phone}" OR "{national or phone}" OR "{dashed or phone}" '
            f'(CNAM OR "caller id" OR "caller-id" OR "reverse phone" OR "phone owner")',
        )
        add(
            "Google — people-search mentions (manual)",
            f'"{dashed or phone}" OR "{paren or phone}" '
            f"(whitepages OR thatsthem OR spokeo OR truepeoplesearch OR fastpeoplesearch OR 411)",
        )
        add("Google — phone + WhatsApp/Telegram", f'"{phone}" (whatsapp OR telegram OR signal)')

        add("Manual reverse lookup — Whitepages", dashed or phone)
        links[-1].url = _whitepages_phone_url(variants)
        add("Manual reverse lookup — Thatsthem", dashed or phone)
        links[-1].url = _thatsthem_phone_url(variants)
        add("Manual reverse lookup — FastPeopleSearch", dashed or phone)
        links[-1].url = _fastpeople_phone_url(variants)
        add("Manual reverse lookup — TruePeopleSearch", paren or dashed or phone)
        links[-1].url = _truepeople_phone_url(variants)
        add("Manual reverse lookup — Spokeo", dashed or phone)
        links[-1].url = _spokeo_phone_url(variants)
        add("Manual reverse lookup — 411", dashed or phone)
        links[-1].url = _four11_phone_url(variants)
        add("Truecaller web search (manual)", phone)
        links[-1].url = f"https://www.truecaller.com/search/{quote_plus(phone)}"
        add("Google — Whitepages-style owner query", f'"{intl or phone}" phone owner')
    elif query.type == QueryType.name and query.name:
        name = query.name
        add("Google — quoted name", f'"{name}"')
        add("DuckDuckGo — name", f'"{name}"', "ddg")
        add("Bing — name", f'"{name}"', "bing")
        add("Google — name + email", f'"{name}" ("@" OR email OR contact)')
        add("LinkedIn people", f'site:linkedin.com/in "{name}"')
        add("Facebook people", f'site:facebook.com "{name}"')
        add("Twitter / X", f'site:x.com "{name}" OR site:twitter.com "{name}"')
        add("News / press", f'"{name}" (interview OR biography OR "is a")')
        add("Whitepages-style public records search", f'"{name}" (address OR phone OR "public records")')
        add("FastPeopleSearch-style query (manual)", name)
        links[-1].url = f"https://www.fastpeoplesearch.com/name/{quote_plus(name.replace(' ', '-'))}"
        add("BeenVerified is paid — skip; use this Google instead", f'"{name}" "obituary" OR "county" OR voter')
    else:
        user = query.username or raw.lstrip("@")
        add("Google — exact username", f'"{user}"')
        add("DuckDuckGo — username", f'"{user}"', "ddg")
        add("Bing — username", f'"{user}"', "bing")
        add("Google — username + social", f'"{user}" (twitter OR instagram OR github OR telegram)')
        add("LinkedIn", f'site:linkedin.com "{user}"')
        add("GitHub users", f'site:github.com "{user}"')
        add("Reddit", f'site:reddit.com/user "{user}" OR site:reddit.com "{user}"')
        add("TikTok", f'site:tiktok.com "@{user}"')
        add("KnowEm-style check (manual Google)", f'"{user}" account OR profile -password')

    # Shared hygiene / pivot links
    add("Wayback Machine", raw)
    links[-1].url = f"https://web.archive.org/web/*/{quote_plus(raw)}"
    add("IntelTechniques search forms (manual)", "OSINT tools directory")
    links[-1].url = "https://inteltechniques.com/tools/"

    return links


def _phone_text_variants(query: Query) -> dict[str, str]:
    raw = query.phone_e164 or query.raw
    e164 = query.phone_e164 or ""
    national = query.phone_national or ""
    parsed = None
    try:
        parsed = phonenumbers.parse(raw, "US")
    except NumberParseException:
        parsed = None
    if parsed:
        e164 = e164 or phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        national = national or str(parsed.national_number)
        intl = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        region = phonenumbers.region_code_for_number(parsed) or ""
    else:
        intl = e164 or raw
        region = ""

    digits = re.sub(r"\D", "", national or e164 or raw)
    dashed = ""
    dotted = ""
    paren = ""
    if region == "US" and len(digits) == 10:
        a, b, c = digits[:3], digits[3:6], digits[6:]
        dashed = f"{a}-{b}-{c}"
        dotted = f"{a}.{b}.{c}"
        paren = f"({a}) {b}-{c}"
    elif len(digits) >= 8:
        dashed = digits
        dotted = digits
        paren = digits
    return {
        "e164": e164,
        "national": national or digits,
        "international": intl,
        "dashed": dashed,
        "dotted": dotted,
        "paren": paren,
        "region": region,
        "digits": digits,
    }


def _us_triple(variants: dict[str, str]) -> tuple[str, str, str] | None:
    digits = variants.get("digits") or ""
    if variants.get("region") == "US" and len(digits) == 10:
        return digits[:3], digits[3:6], digits[6:]
    return None


def _google_phone_fallback(variants: dict[str, str]) -> str:
    q = variants.get("e164") or variants.get("national") or ""
    return f"https://www.google.com/search?q={quote_plus(q)}"


def _whitepages_phone_url(variants: dict[str, str]) -> str:
    triple = _us_triple(variants)
    if triple:
        a, b, c = triple
        return f"https://www.whitepages.com/phone/1-{a}-{b}-{c}"
    return _google_phone_fallback(variants)


def _thatsthem_phone_url(variants: dict[str, str]) -> str:
    triple = _us_triple(variants)
    if triple:
        a, b, c = triple
        return f"https://thatsthem.com/phone/{a}-{b}-{c}"
    return _google_phone_fallback(variants)


def _fastpeople_phone_url(variants: dict[str, str]) -> str:
    triple = _us_triple(variants)
    if triple:
        a, b, c = triple
        return f"https://www.fastpeoplesearch.com/{a}-{b}-{c}"
    return _google_phone_fallback(variants)


def _truepeople_phone_url(variants: dict[str, str]) -> str:
    triple = _us_triple(variants)
    if triple:
        a, b, c = triple
        return f"https://www.truepeoplesearch.com/resultphone?phoneno=({a}){b}-{c}"
    return _google_phone_fallback(variants)


def _spokeo_phone_url(variants: dict[str, str]) -> str:
    triple = _us_triple(variants)
    if triple:
        a, b, c = triple
        return f"https://www.spokeo.com/{a}-{b}-{c}"
    return _google_phone_fallback(variants)


def _four11_phone_url(variants: dict[str, str]) -> str:
    triple = _us_triple(variants)
    if triple:
        a, b, c = triple
        return f"https://www.411.com/phone/1-{a}-{b}-{c}"
    return _google_phone_fallback(variants)
