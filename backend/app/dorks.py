from __future__ import annotations

from urllib.parse import quote_plus

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
        phone = query.phone_e164 or raw
        add("Google — exact phone", f'"{phone}"')
        add("DuckDuckGo — phone", f'"{phone}"', "ddg")
        add("Bing — phone", f'"{phone}"', "bing")
        add("Google — phone + WhatsApp/Telegram", f'"{phone}" (whatsapp OR telegram OR signal)')
        add("Truecaller web search (manual)", phone)
        links[-1].url = f"https://www.truecaller.com/search/{quote_plus(phone)}"
        add("Whitepages-style name lookup", f'"{phone}" phone owner')
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
