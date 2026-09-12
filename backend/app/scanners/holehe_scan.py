from __future__ import annotations

import asyncio
import importlib
import os
import pkgutil
from typing import Any

from app.config import HOLEHE_TIMEOUT
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner


def _load_holehe() -> tuple[Any, Any] | None:
    try:
        import holehe.modules as modules
        import httpx
        import trio
    except Exception:
        return None
    return modules, (httpx, trio)


def _collect_functions(modules_pkg: Any) -> list[Any]:
    websites: list[Any] = []

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
            site = full.split(".")[-1]
            fn = getattr(mod, site, None)
            if callable(fn):
                websites.append(fn)

    walk(modules_pkg)
    return websites


class HoleheScanner(Scanner):
    id = "holehe"
    name = "Holehe"
    tool = "holehe"
    description = (
        "Checks whether an email appears registered on 100+ sites via public "
        "password-reset / account-existence endpoints. Does not log into accounts."
    )
    accepts = [QueryType.email]
    limitations = (
        "False negatives are common when a site rate-limits or changes its API. "
        "A miss is not proof the email is unused. Does not return passwords or dumps."
    )
    timeout = HOLEHE_TIMEOUT
    heavy = True

    def available(self) -> bool:
        return _load_holehe() is not None

    async def run(self, query: Query) -> ScannerResult:
        loaded = _load_holehe()
        if loaded is None:
            return self._result(
                "unavailable",
                "holehe is not installed",
                error="Import failed — pip install holehe",
            )
        email = query.email
        if not email:
            return self._result("skipped", "No email on this query")

        modules_pkg, (httpx, trio) = loaded
        functions = _collect_functions(modules_pkg)
        if not functions:
            return self._result(
                "unavailable",
                "holehe modules could not be loaded",
                error="No holehe site modules found",
            )

        wall = float(os.getenv("HOLEHE_TIMEOUT", self.timeout))
        pad = 5.0 if wall >= 20 else max(0.05, wall * 0.2)
        inner = max(0.05, wall - pad)

        def _sync() -> tuple[list[dict[str, Any]], bool]:
            async def _scan() -> tuple[list[dict[str, Any]], bool]:
                out: list[dict[str, Any]] = []
                client = httpx.AsyncClient(timeout=8.0)
                timed_out = False
                try:
                    with trio.move_on_after(inner) as cancel_scope:
                        async with trio.open_nursery() as nursery:
                            for fn in functions:
                                nursery.start_soon(self._launch, fn, email, client, out)
                    timed_out = cancel_scope.cancelled_caught
                finally:
                    await client.aclose()
                return out, timed_out

            return trio.run(_scan)

        try:
            raw, timed_out = await asyncio.to_thread(_sync)
        except Exception as exc:
            return self._result("error", "holehe failed", error=str(exc))

        findings, exists, limited = self._findings_from_raw(raw)
        summary = (
            f"{len(exists)} site(s) report this email as registered"
            if exists
            else "No site reported a registration"
        )
        if limited:
            summary += f" · {len(limited)} rate-limited"
        raw_payload = {
            "checked": len(raw),
            "exists": exists,
            "rate_limited": [r.get("domain") for r in limited],
            "partial": timed_out,
        }
        if timed_out:
            if findings:
                summary += " · partial (timed out)"
            return self._result(
                "timeout",
                summary if findings else f"Timed out after {int(inner)}s",
                findings=findings,
                raw=raw_payload,
                error="timeout",
            )
        return self._result(
            "success",
            summary,
            findings=findings,
            raw=raw_payload,
        )

    def _findings_from_raw(
        self, raw: list[dict[str, Any]]
    ) -> tuple[list[Finding], list[dict[str, Any]], list[dict[str, Any]]]:
        findings: list[Finding] = []
        exists = [r for r in raw if r.get("exists") and not r.get("rateLimit")]
        limited = [r for r in raw if r.get("rateLimit")]
        for row in exists:
            extra = {
                k: v
                for k, v in row.items()
                if k
                in {
                    "emailrecovery",
                    "phoneNumber",
                    "others",
                    "domain",
                    "method",
                }
                and v
            }
            domain = row.get("domain") or row.get("name") or "unknown"
            raw_url = row.get("url") or row.get("link")
            if not raw_url and domain and "." in str(domain):
                raw_url = f"https://{domain}"
            url = str(raw_url) if is_concrete_profile_url(
                raw_url if isinstance(raw_url, str) else None
            ) else None
            findings.append(
                Finding(
                    kind="profile" if url else "note",
                    title=str(row.get("name") or domain),
                    value=f"Email registered on {domain}",
                    url=url,
                    extra=extra,
                )
            )
        return findings, exists, limited

    @staticmethod
    async def _launch(module: Any, email: str, client: Any, out: list) -> None:
        try:
            await module(email, client, out)
        except Exception:
            return
