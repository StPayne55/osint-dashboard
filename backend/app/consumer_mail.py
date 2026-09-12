from __future__ import annotations

# Free / consumer mailbox providers. Harvesting crt.sh for these domains
# returns certificate-transparency noise (hundreds of unrelated addresses),
# not colleagues of the person being looked up.
CONSUMER_MAIL_EXACT = {
    "aol.com",
    "att.net",
    "bellsouth.net",
    "bigpond.com",
    "bk.ru",
    "btinternet.com",
    "btopenworld.com",
    "charter.net",
    "comcast.net",
    "cox.net",
    "daum.net",
    "disroot.org",
    "duck.com",
    "earthlink.net",
    "email.com",
    "fastmail.com",
    "fastmail.fm",
    "foxmail.com",
    "freenet.de",
    "frontier.com",
    "gmail.com",
    "gmx.com",
    "gmx.de",
    "gmx.net",
    "googlemail.com",
    "hanmail.net",
    "hey.com",
    "hotmail.com",
    "hushmail.com",
    "i.ua",
    "icloud.com",
    "inbox.com",
    "inbox.ru",
    "interia.pl",
    "laposte.net",
    "libero.it",
    "list.ru",
    "live.com",
    "lycos.com",
    "mac.com",
    "mail.com",
    "mail.ru",
    "mailbox.org",
    "mailfence.com",
    "me.com",
    "msn.com",
    "naver.com",
    "o2.pl",
    "optonline.net",
    "optusnet.com.au",
    "orange.fr",
    "outlook.com",
    "pm.me",
    "posteo.de",
    "posteo.net",
    "proton.me",
    "protonmail.com",
    "qq.com",
    "rediffmail.com",
    "riseup.net",
    "rocketmail.com",
    "runbox.com",
    "sbcglobal.net",
    "seznam.cz",
    "skiff.com",
    "t-online.de",
    "tuta.com",
    "tutamail.com",
    "tutanota.com",
    "ukr.net",
    "usa.com",
    "verizon.net",
    "virgilio.it",
    "wanadoo.fr",
    "web.de",
    "wp.pl",
    "ya.ru",
    "yahoo.com",
    "yandex.com",
    "yandex.ru",
    "ymail.com",
    "zoho.com",
    "zohomail.com",
    "126.com",
    "163.com",
    "yeah.net",
}

# First label of domains such as yahoo.co.uk, hotmail.fr, gmx.at, yandex.kz.
CONSUMER_MAIL_PREFIXES = {
    "gmx",
    "hotmail",
    "icloud",
    "live",
    "outlook",
    "yahoo",
    "yandex",
}

HARVEST_EMAIL_CAP = 25


def normalize_domain(domain: str | None) -> str:
    return (domain or "").strip().lower().rstrip(".")


def is_consumer_mail_domain(domain: str | None) -> bool:
    d = normalize_domain(domain)
    if not d:
        return False
    if d in CONSUMER_MAIL_EXACT:
        return True
    head = d.split(".", 1)[0]
    return head in CONSUMER_MAIL_PREFIXES


def email_local_part(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[0].strip().lower()


def email_domain(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return normalize_domain(email.split("@", 1)[1])


def on_company_domain(email: str, domain: str | None) -> bool:
    """True when the address is on the queried company domain or a subdomain of it."""
    d = normalize_domain(domain)
    ed = email_domain(email)
    if not d or not ed:
        return False
    return ed == d or ed.endswith("." + d)


def keep_harvested_email(email: str, query_email: str | None, domain: str | None) -> bool:
    """Keep harvested addresses that belong to this lookup, not crt.sh noise."""
    addr = (email or "").strip().lower()
    if not addr or "@" not in addr:
        return False
    q = (query_email or "").strip().lower()
    if q and addr == q:
        return True
    q_local = email_local_part(q)
    if q_local and email_local_part(addr) == q_local:
        return True
    return on_company_domain(addr, domain)
