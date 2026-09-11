from __future__ import annotations

import asyncio
from typing import Any

from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner

# Common throwaway / forwarding domains. Not exhaustive — a hit is a hint.
DISPOSABLE = {
    "10minutemail.com",
    "guerrillamail.com",
    "guerrillamail.net",
    "mailinator.com",
    "tempmail.com",
    "temp-mail.org",
    "yopmail.com",
    "trashmail.com",
    "sharklasers.com",
    "getnada.com",
    "maildrop.cc",
    "dispostable.com",
    "fakeinbox.com",
    "throwaway.email",
    "mailnesia.com",
    "tempail.com",
    "moakt.com",
    "emailondeck.com",
    "mintemail.com",
    "mytemp.email",
    "discard.email",
    "trashmailer.com",
    "getairmail.com",
    "mailcatch.com",
    "inboxkitten.com",
    "simplelogin.com",
    "simplelogin.co",
    "anonaddy.com",
    "addy.io",
    "relay.firefox.com",
    "duck.com",
}

ROLE_LOCAL = {
    "admin",
    "administrator",
    "info",
    "contact",
    "hello",
    "support",
    "sales",
    "billing",
    "noreply",
    "no-reply",
    "donotreply",
    "webmaster",
    "postmaster",
    "abuse",
    "security",
    "privacy",
    "hr",
    "jobs",
    "press",
    "media",
    "team",
    "office",
}


class EmailIntelScanner(Scanner):
    id = "email_intel"
    name = "Email MX / disposable"
    tool = "dnspython + built-in lists"
    description = (
        "Looks up MX records for the email domain, flags common disposable or "
        "alias providers, and tags role-style local parts (info@, admin@)."
    )
    accepts = [QueryType.email]
    limitations = (
        "Disposable list is a static hint, not a live blocklist. MX presence does "
        "not prove the mailbox exists."
    )
    timeout = 12.0

    async def run(self, query: Query) -> ScannerResult:
        email = query.email
        domain = query.domain
        if not email or not domain:
            return self._result("skipped", "No email")
        local = email.split("@", 1)[0]
        findings: list[Finding] = [
            Finding(kind="email", title="Normalized", value=email)
        ]
        if local.lower() in ROLE_LOCAL:
            findings.append(
                Finding(
                    kind="note",
                    title="Role account",
                    value=f'Local-part "{local}" looks like a shared / role mailbox, not a person.',
                )
            )
        if domain in DISPOSABLE or domain.endswith(".onion"):
            findings.append(
                Finding(
                    kind="note",
                    title="Disposable / alias domain",
                    value=f"{domain} is a known throwaway or forwarding provider.",
                )
            )

        mx = await asyncio.to_thread(self._mx, domain)
        if mx.get("error"):
            findings.append(
                Finding(kind="note", title="MX lookup", value=f"DNS error: {mx['error']}")
            )
        elif mx.get("records"):
            for rec in mx["records"]:
                findings.append(
                    Finding(
                        kind="metadata",
                        title=f"MX {rec['priority']}",
                        value=rec["host"],
                    )
                )
        else:
            findings.append(
                Finding(
                    kind="note",
                    title="MX lookup",
                    value=f"No MX records for {domain} — domain may not accept mail.",
                )
            )

        summary = (
            f"{domain} · {len(mx.get('records') or [])} MX"
            if mx.get("records")
            else f"{domain} · no MX"
        )
        return self._result("success", summary, findings=findings, raw=mx)

    def _mx(self, domain: str) -> dict[str, Any]:
        try:
            import dns.resolver
        except Exception as exc:
            return {"error": f"dnspython missing: {exc}"}
        try:
            answers = dns.resolver.resolve(domain, "MX")
            records = []
            for rdata in answers:
                host = str(rdata.exchange).rstrip(".")
                if not host:
                    host = "(null MX — domain does not accept mail)"
                records.append({"priority": int(rdata.preference), "host": host})
            records.sort(key=lambda r: r["priority"])
            return {"records": records}
        except Exception as exc:
            return {"error": str(exc), "records": []}
