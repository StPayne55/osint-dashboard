from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from app.config import HARVESTER_TIMEOUT, USER_AGENT
from app.models import Finding, Query, QueryType, ScannerResult
from app.scanners.base import Scanner

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class HarvesterScanner(Scanner):
    id = "harvester"
    name = "theHarvester / CT"
    tool = "theHarvester + crt.sh + HackerTarget"
    description = (
        "When the query has a domain (from an email), gathers publicly listed "
        "hostnames and emails via certificate transparency (crt.sh) and HackerTarget. "
        "Also calls a theHarvester CLI/library if one is actually present."
    )
    accepts = [QueryType.email, QueryType.name]
    limitations = (
        "theHarvester is domain-oriented, not a people-search. A personal name "
        "without a domain only gets an honest skip plus the dork pack. Free "
        "sources are noisy and often rate-limited."
    )
    timeout = HARVESTER_TIMEOUT

    def applicable(self, query: Query) -> bool:
        return bool(query.domain or query.type == QueryType.name)

    async def run(self, query: Query) -> ScannerResult:
        if query.type == QueryType.name and not query.domain:
            return self._result(
                "skipped",
                "Name-only queries have no domain to harvest. Use the search-link pack.",
                findings=[
                    Finding(
                        kind="note",
                        title="No domain",
                        value=(
                            "theHarvester enumerates emails and hosts for a company domain. "
                            "It cannot produce a home address or phone from a name. "
                            "Open the Search links section for Google / LinkedIn / Whitepages-style queries."
                        ),
                    )
                ],
            )
        domain = query.domain
        if not domain:
            return self._result("skipped", "No domain")

        crt, hacker, hv = await asyncio.gather(
            self._crtsh(domain),
            self._hackertarget(domain),
            asyncio.to_thread(self._theharvester, domain),
        )
        if hv.get("unavailable"):
            cli = await asyncio.to_thread(self._theharvester_cli, domain)
            if cli:
                hv = cli

        emails: set[str] = set()
        hosts: set[str] = set()
        notes: list[str] = []
        for blob in (crt, hacker, hv):
            emails.update(blob.get("emails") or [])
            hosts.update(blob.get("hosts") or [])
            if blob.get("note"):
                notes.append(str(blob["note"]))
            if blob.get("error"):
                notes.append(str(blob["error"]))

        findings: list[Finding] = []
        for email in sorted(emails):
            findings.append(Finding(kind="email", title="Public email", value=email))
        for host in sorted(hosts)[:80]:
            findings.append(
                Finding(
                    kind="metadata",
                    title="Hostname",
                    value=host,
                    url=f"https://{host}" if not host.startswith("*") else None,
                )
            )
        for note in notes:
            findings.append(Finding(kind="note", title="Source note", value=note))

        summary = f"{len(emails)} email(s), {len(hosts)} host(s) for {domain}"
        return self._result(
            "success",
            summary,
            findings=findings,
            raw={"crtsh": crt, "hackertarget": hacker, "theharvester": hv},
        )

    async def _crtsh(self, domain: str) -> dict[str, Any]:
        url = f"https://crt.sh/?q={domain}&output=json"
        try:
            async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {"error": f"crt.sh HTTP {resp.status_code}", "hosts": [], "emails": []}
                data = resp.json()
        except Exception as exc:
            return {"error": f"crt.sh: {exc}", "hosts": [], "emails": []}
        hosts: set[str] = set()
        emails: set[str] = set()
        if isinstance(data, list):
            for row in data[:400]:
                name = str(row.get("name_value") or "")
                for part in re.split(r"[\s,]+", name):
                    part = part.strip().lower()
                    if EMAIL_RE.fullmatch(part):
                        emails.add(part)
                    elif domain in part:
                        hosts.add(part.lstrip("*."))
        return {"hosts": sorted(hosts), "emails": sorted(emails), "note": "crt.sh certificate transparency"}

    async def _hackertarget(self, domain: str) -> dict[str, Any]:
        url = f"https://api.hackertarget.com/hostsearch/?q={domain}"
        try:
            async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(url)
                text = resp.text.strip()
        except Exception as exc:
            return {"error": f"HackerTarget: {exc}", "hosts": [], "emails": []}
        if "error" in text.lower() and len(text) < 200:
            return {"error": f"HackerTarget: {text}", "hosts": [], "emails": []}
        if "api count exceeded" in text.lower():
            return {"error": "HackerTarget rate limited", "hosts": [], "emails": []}
        hosts = []
        for line in text.splitlines():
            host = line.split(",")[0].strip().lower()
            if host and domain in host:
                hosts.append(host)
        return {"hosts": hosts, "emails": [], "note": "HackerTarget hostsearch"}

    def _theharvester(self, domain: str) -> dict[str, Any]:
        """Best-effort theHarvester. Degrades if the package or sources fail."""
        try:
            return asyncio.run(self._theharvester_async(domain))
        except Exception as exc:
            return {"error": f"theHarvester: {exc}", "hosts": [], "emails": []}

    async def _theharvester_async(self, domain: str) -> dict[str, Any]:
        emails: set[str] = set()
        hosts: set[str] = set()
        used: list[str] = []
        try:
            from theHarvester.discovery import crtsh as crtsh_mod  # type: ignore
        except Exception:
            crtsh_mod = None
        try:
            from theHarvester.discovery import hackertarget as ht_mod  # type: ignore
        except Exception:
            ht_mod = None
        try:
            from theHarvester.discovery import urlscan as urlscan_mod  # type: ignore
        except Exception:
            urlscan_mod = None

        async def _run_source(name: str, cls: Any) -> None:
            try:
                searcher = cls(domain)
                do = getattr(searcher, "do_search", None)
                if do is None:
                    return
                result = do()
                if asyncio.iscoroutine(result):
                    await result
                get_emails = getattr(searcher, "get_emails", None)
                get_hosts = getattr(searcher, "get_hostnames", None) or getattr(
                    searcher, "get_hostnames", None
                )
                if callable(get_emails):
                    got = get_emails()
                    if asyncio.iscoroutine(got):
                        got = await got
                    for item in got or []:
                        emails.add(str(item).lower())
                if callable(get_hosts):
                    got = get_hosts()
                    if asyncio.iscoroutine(got):
                        got = await got
                    for item in got or []:
                        hosts.add(str(item).lower())
                used.append(name)
            except Exception:
                return

        if crtsh_mod is not None:
            cls = getattr(crtsh_mod, "SearchCrtsh", None)
            if cls:
                await _run_source("theHarvester.crtsh", cls)
        if ht_mod is not None:
            cls = getattr(ht_mod, "SearchHackerTarget", None)
            if cls:
                await _run_source("theHarvester.hackertarget", cls)
        if urlscan_mod is not None:
            cls = getattr(urlscan_mod, "SearchUrlscan", None)
            if cls:
                await _run_source("theHarvester.urlscan", cls)

        if not used:
            return {
                "unavailable": True,
                "note": "theHarvester Python package is not usable on this interpreter (current upstream wants 3.14; PyPI 0.0.1 is a stub). Public crt.sh + HackerTarget adapters still ran.",
                "hosts": [],
                "emails": [],
            }
        return {"hosts": sorted(hosts), "emails": sorted(emails), "note": "theHarvester: " + ", ".join(used)}

    def _theharvester_cli(self, domain: str) -> dict[str, Any] | None:
        import shutil
        import subprocess

        binary = shutil.which("theHarvester") or shutil.which("theharvester")
        if not binary:
            return None
        try:
            proc = subprocess.run(
                [binary, "-d", domain, "-b", "crtsh,hackertarget", "-l", "50"],
                capture_output=True,
                text=True,
                timeout=40,
            )
        except Exception as exc:
            return {"error": f"theHarvester CLI: {exc}", "hosts": [], "emails": []}
        emails = {m.lower() for m in EMAIL_RE.findall(proc.stdout or "")}
        hosts = set()
        for line in (proc.stdout or "").splitlines():
            line = line.strip().lower()
            if domain in line and " " not in line and "@" not in line:
                hosts.add(line)
        return {
            "hosts": sorted(hosts),
            "emails": sorted(emails),
            "note": "theHarvester CLI",
        }
