from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import (
    SPIDERFOOT_HOME,
    SPIDERFOOT_MAX_THREADS,
    SPIDERFOOT_MODULES,
    SPIDERFOOT_REMOTE_TIMEOUT,
    SPIDERFOOT_TIMEOUT,
    SPIDERFOOT_USECASE,
    USER_AGENT,
    env_flag,
)
from app.models import Finding, Query, QueryType, ScannerResult
from app.profile_urls import is_concrete_profile_url
from app.scanners.base import Scanner

# Account / social modules that work without paid keys. Breach, dump, and
# dark-web modules are omitted on purpose (policy + most need API keys).
DEFAULT_MODULES = (
    "sfp_accounts",
    "sfp_social",
    "sfp_github",
    "sfp_twitter",
    "sfp_instagram",
    "sfp_gravatar",
    "sfp_keybase",
    "sfp_myspace",
    "sfp_slideshare",
    "sfp_flickr",
    "sfp_venmo",
)

# stdout -F matches SpiderFoot event *codes*, not the human labels.
OUTPUT_TYPE_CODES = (
    "ACCOUNT_EXTERNAL_OWNED",
    "SIMILAR_ACCOUNT_EXTERNAL",
    "SOCIAL_MEDIA",
    "USERNAME",
    "EMAILADDR",
    "HUMAN_NAME",
    "PHONE_NUMBER",
)

_SKIP_TYPE_NEEDLES = (
    "compromised",
    "hacked",
    "breach",
    "dark",
    "onion",
    "leak",
    "paste",
    "malware",
    "blacklist",
    "threat",
    "password",
)

_TYPE_ALIASES = {
    "account on external site": "ACCOUNT_EXTERNAL_OWNED",
    "similar account on external site": "SIMILAR_ACCOUNT_EXTERNAL",
    "social media presence": "SOCIAL_MEDIA",
    "username": "USERNAME",
    "email address": "EMAILADDR",
    "human name": "HUMAN_NAME",
    "phone number": "PHONE_NUMBER",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_SFURL_RE = re.compile(r"<SFURL>(.*?)</SFURL>", re.IGNORECASE | re.DOTALL)
_ACCOUNT_PLATFORM_RE = re.compile(r"^(.+?)\s*\(Category:", re.IGNORECASE)
_SOCIAL_PLATFORM_RE = re.compile(r"^([^:]+):\s*(https?://\S+)", re.IGNORECASE)

_VALID_USECASES = {"passive", "footprint", "investigate", "all"}


def sf_home() -> Path:
    return Path(os.getenv("SPIDERFOOT_HOME", SPIDERFOOT_HOME) or "/opt/spiderfoot")


def sf_script_path() -> Path | None:
    script = sf_home() / "sf.py"
    if script.is_file():
        return script
    return None


def sf_python() -> str:
    explicit = os.getenv("SPIDERFOOT_PYTHON", "").strip()
    if explicit:
        return explicit
    venv = sf_home() / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    return sys.executable


def spiderfoot_enabled() -> bool:
    """Off unless SPIDERFOOT_ENABLED is an explicit truthy value. Missing = off."""
    return env_flag("SPIDERFOOT_ENABLED", default=False)


def spiderfoot_runner_url() -> str:
    """Base URL for the dedicated runner. Accepts host:port from Render fromService."""
    raw = os.getenv("SPIDERFOOT_URL", "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")


def spiderfoot_runner_token() -> str:
    return os.getenv("SPIDERFOOT_RUNNER_TOKEN", "").strip()


def remote_configured() -> bool:
    """Remote mode is on when both URL and bearer token are set (ENABLED not required)."""
    return bool(spiderfoot_runner_url() and spiderfoot_runner_token())


def derive_target(query: Query) -> str | None:
    """Pick a SpiderFoot target. Prefer a typed identity, then username hints."""
    if query.type == QueryType.email and query.email:
        return query.email
    if query.type == QueryType.phone and (query.phone_e164 or query.raw):
        return query.phone_e164 or query.raw
    if query.type == QueryType.name and query.name:
        return query.name
    if query.username:
        return query.username.lstrip("@")
    if query.email:
        return query.email.split("@", 1)[0]
    if query.username_candidates:
        return query.username_candidates[0]
    if query.name:
        return query.name
    if query.phone_e164:
        return query.phone_e164
    return None


def parse_spiderfoot_stdout(stdout: str) -> list[dict[str, Any]]:
    """Parse CLI ``-o json`` output, including a truncated array after timeout."""
    if not stdout or not stdout.strip():
        return []
    text = stdout.strip()
    start = text.find("[")
    if start == -1:
        return _decode_json_objects(text)
    blob = text[start:]
    end = blob.rfind("]")
    candidates = [blob]
    if end != -1:
        candidates.insert(0, blob[: end + 1])
    else:
        candidates.insert(0, blob.rstrip().rstrip(",") + "]")
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            return [data]
    return _decode_json_objects(blob)


def _decode_json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    events: list[dict[str, Any]] = []
    idx = 0
    length = len(text)
    while idx < length:
        while idx < length and text[idx] in " \t\r\n,[":
            idx += 1
        if idx >= length or text[idx] == "]":
            break
        try:
            obj, nxt = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            events.append(obj)
        idx = nxt
    return events


def _normalize_type(event: dict[str, Any]) -> str:
    raw = str(event.get("type") or event.get("eventType") or "").strip()
    if not raw:
        return ""
    key = raw.replace("-", " ").replace("_", " ").lower()
    compact = key.replace(" ", "")
    for code in (
        "ACCOUNT_EXTERNAL_OWNED",
        "SIMILAR_ACCOUNT_EXTERNAL",
        "SOCIAL_MEDIA",
        "USERNAME",
        "EMAILADDR",
        "HUMAN_NAME",
        "PHONE_NUMBER",
        "EMAILADDR_COMPROMISED",
        "ACCOUNT_EXTERNAL_OWNED_COMPROMISED",
    ):
        if raw.upper() == code or compact == code.replace("_", "").lower():
            return code
    return _TYPE_ALIASES.get(key, raw.upper().replace(" ", "_"))


def _skip_event_type(type_code: str) -> bool:
    lowered = type_code.lower().replace("_", " ")
    return any(needle in lowered for needle in _SKIP_TYPE_NEEDLES)


def _extract_urls(text: str) -> list[str]:
    found: list[str] = []
    for match in _SFURL_RE.findall(text or ""):
        url = match.strip().rstrip(".,;:)")
        if url and url not in found:
            found.append(url)
    for match in _URL_RE.findall(text or ""):
        url = match.rstrip(".,;:)")
        if url and url not in found:
            found.append(url)
    return found


def _platform_and_url(type_code: str, data: str) -> tuple[str, str | None]:
    text = (data or "").strip()
    social = _SOCIAL_PLATFORM_RE.match(text)
    if social:
        return social.group(1).strip(), social.group(2).rstrip(".,;:)")
    account = _ACCOUNT_PLATFORM_RE.match(text)
    urls = _extract_urls(text)
    url = urls[0] if urls else None
    if account:
        return account.group(1).strip(), url
    if url:
        host = (urlparse(url).hostname or "").removeprefix("www.")
        title = host.split(".")[0].title() if host else type_code.replace("_", " ").title()
        return title, url
    return type_code.replace("_", " ").title(), None


def events_to_findings(events: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()

    def add(finding: Finding) -> None:
        key = f"{finding.kind}|{finding.title}|{finding.value}|{finding.url or ''}"
        if key in seen:
            return
        seen.add(key)
        findings.append(finding)

    for event in events:
        type_code = _normalize_type(event)
        if not type_code or _skip_event_type(type_code):
            continue
        data = event.get("data")
        if data is None:
            continue
        data_text = data if isinstance(data, str) else str(data)
        module = str(event.get("module") or "")
        extra = {"module": module, "sf_type": type_code}
        platform, url = _platform_and_url(type_code, data_text)

        if type_code in {"ACCOUNT_EXTERNAL_OWNED", "SIMILAR_ACCOUNT_EXTERNAL", "SOCIAL_MEDIA"}:
            if is_concrete_profile_url(url):
                add(
                    Finding(
                        kind="profile",
                        title=platform,
                        value=url or data_text.strip(),
                        url=url,
                        extra=extra,
                    )
                )
            continue

        if type_code == "USERNAME":
            handle = data_text.strip().lstrip("@")
            if handle:
                add(Finding(kind="username", title="Username", value=handle, extra=extra))
            continue

        if type_code == "EMAILADDR":
            email = data_text.strip()
            if email and "@" in email:
                add(Finding(kind="email", title="Public email", value=email, extra=extra))
            continue

        if url and is_concrete_profile_url(url):
            add(
                Finding(
                    kind="profile",
                    title=platform,
                    value=url,
                    url=url,
                    extra=extra,
                )
            )

    return findings


def selected_modules() -> list[str] | None:
    raw = os.getenv("SPIDERFOOT_MODULES", SPIDERFOOT_MODULES).strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return None


def selected_usecase() -> str | None:
    raw = os.getenv("SPIDERFOOT_USECASE", SPIDERFOOT_USECASE).strip().lower()
    if raw in _VALID_USECASES:
        return raw
    return None


class SpiderFootScanner(Scanner):
    id = "spiderfoot"
    name = "SpiderFoot"
    tool = "spiderfoot (OSS)"
    description = (
        "Open-source SpiderFoot CLI (not SpiderFoot HX). Prefers the dedicated "
        "spiderfoot-runner HTTP API when SPIDERFOOT_URL is set; otherwise a "
        "local sf.py fallback. Account/social modules only."
    )
    accepts = [QueryType.username, QueryType.email, QueryType.name, QueryType.phone]
    limitations = (
        "Set SPIDERFOOT_URL + SPIDERFOOT_RUNNER_TOKEN to call the Starter "
        "private runner (local SPIDERFOOT_ENABLED is not required). Local "
        "in-process CLI stays off unless SPIDERFOOT_ENABLED=1 and sf.py is "
        "installed. Social/account allowlist only; breach/dark-web modules "
        "are not enabled. Deep/full-module scans are a future optional. "
        "Missing runner or binary → unavailable, not a crash."
    )
    heavy = True

    @property
    def timeout(self) -> float:  # type: ignore[override]
        # jobs.py asyncio.wait_for() uses this. Remote HTTP waits wall+30,
        # so the job gate needs extra slack to receive a structured timeout.
        wall = self._wall_timeout()
        if remote_configured():
            return wall + 45.0
        return wall

    def available(self) -> bool:
        if remote_configured():
            return True
        return spiderfoot_enabled() and sf_script_path() is not None

    def applicable(self, query: Query) -> bool:
        return bool(derive_target(query))

    async def run(self, query: Query) -> ScannerResult:
        target = derive_target(query)
        if not target:
            return self._result("skipped", "No username, email, name, or phone target")

        if remote_configured():
            return await self._run_remote(target)

        if not spiderfoot_enabled():
            return self._result(
                "unavailable",
                "SpiderFoot disabled (SPIDERFOOT_ENABLED=0)",
                error="disabled",
            )
        script = sf_script_path()
        if script is None:
            return self._result(
                "unavailable",
                "SpiderFoot OSS is not installed in this environment",
                error=f"sf.py not found under {sf_home()}",
            )

        try:
            # Popen.communicate() is blocking; never run it on the asyncio loop
            # (single-worker uvicorn on Render would freeze health/report/SSE).
            stdout, status, error = await asyncio.to_thread(self._run_cli, target, script)
        except Exception as exc:
            return self._result("error", "SpiderFoot failed", error=str(exc))

        return self._finish(
            target,
            parse_spiderfoot_stdout(stdout),
            status,
            error,
            mode="local",
        )

    def _wall_timeout(self) -> float:
        raw = os.getenv("SPIDERFOOT_TIMEOUT")
        if raw:
            try:
                return max(10.0, float(raw))
            except ValueError:
                pass
        if remote_configured():
            return max(10.0, float(os.getenv("SPIDERFOOT_REMOTE_TIMEOUT", str(SPIDERFOOT_REMOTE_TIMEOUT))))
        return float(SPIDERFOOT_TIMEOUT)

    def _cli_timeout(self) -> float:
        return max(10.0, self._wall_timeout() - 5.0)

    def _remote_scan_timeout(self) -> int:
        return max(10, int(self._wall_timeout()))

    def _finish(
        self,
        target: str,
        events: list[dict[str, Any]],
        status: str,
        error: str | None,
        *,
        mode: str,
        stdout_excerpt: str = "",
        stderr_excerpt: str = "",
        scan_id: str | None = None,
        salvaged: bool = False,
    ) -> ScannerResult:
        findings = events_to_findings(events)
        profiles = sum(1 for f in findings if f.kind == "profile")
        raw = {
            "target": target,
            "events": len(events),
            "modules": selected_modules() or list(DEFAULT_MODULES),
            "usecase": selected_usecase(),
            "partial": status == "timeout",
            "mode": mode,
            "stdout_excerpt": stdout_excerpt,
            "stderr_excerpt": stderr_excerpt,
            "scan_id": scan_id,
            "salvaged": salvaged,
        }
        if status == "timeout":
            summary = (
                f"Timed out after {int(self._wall_timeout())}s"
                + (f" · {profiles} profile(s) so far" if profiles else "")
            )
            return self._result(
                "timeout",
                summary,
                findings=findings,
                raw=raw,
                error=error or "timeout",
            )
        if status == "error":
            return self._result(
                "error",
                "SpiderFoot runner failed" if mode == "remote" else "SpiderFoot CLI failed",
                findings=findings,
                raw=raw,
                error=error,
            )
        summary = (
            f"{profiles} profile URL(s) via SpiderFoot for {target}"
            if profiles
            else f"No SpiderFoot profile URLs for {target}"
        )
        return self._result("success", summary, findings=findings, raw=raw)

    async def _run_remote(self, target: str) -> ScannerResult:
        url = f"{spiderfoot_runner_url()}/v1/scan"
        scan_timeout = self._remote_scan_timeout()
        payload = {
            "target": target,
            "modules": selected_modules() or list(DEFAULT_MODULES),
            "timeout": scan_timeout,
        }
        headers = {
            "Authorization": f"Bearer {spiderfoot_runner_token()}",
            "User-Agent": USER_AGENT,
        }
        # HTTP wait is longer than the runner's own wall clock so we receive
        # a structured timeout payload instead of a dropped connection.
        http_timeout = scan_timeout + 30.0
        try:
            async with httpx.AsyncClient(timeout=http_timeout, headers=headers) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException:
            return self._finish(target, [], "timeout", f"timeout after {int(http_timeout)}s", mode="remote")
        except Exception as exc:
            return self._result("error", "SpiderFoot runner unreachable", error=str(exc)[:500])
        if resp.status_code == 401:
            return self._result("error", "SpiderFoot runner rejected the token", error="401 unauthorized")
        if resp.status_code != 200:
            return self._result(
                "error",
                f"SpiderFoot runner HTTP {resp.status_code}",
                error=(resp.text or "")[:300],
            )
        try:
            body = resp.json()
        except Exception as exc:
            return self._result("error", "SpiderFoot runner returned invalid JSON", error=str(exc)[:300])
        if not isinstance(body, dict):
            return self._result("error", "SpiderFoot runner returned invalid JSON", error="not an object")
        events = body.get("events")
        if not isinstance(events, list):
            events = []
        events = [row for row in events if isinstance(row, dict)]
        status = str(body.get("status") or "error")
        if status not in {"ok", "timeout", "error"}:
            status = "error"
        error = body.get("error")
        excerpt = str(body.get("stdout_excerpt") or "")
        err_excerpt = str(body.get("stderr_excerpt") or "")
        scan_id = body.get("scan_id")
        return self._finish(
            str(body.get("target") or target),
            events,
            status,
            str(error) if error else None,
            mode="remote",
            stdout_excerpt=excerpt[:2000],
            stderr_excerpt=err_excerpt[:2000],
            scan_id=str(scan_id) if scan_id else None,
            salvaged=bool(body.get("salvaged")),
        )

    def _build_command(self, target: str, script: Path) -> list[str]:
        cmd = [
            sf_python(),
            str(script),
            "-s",
            target,
            "-o",
            "json",
            "-q",
            "-n",
            "-max-threads",
            str(max(1, int(os.getenv("SPIDERFOOT_MAX_THREADS", SPIDERFOOT_MAX_THREADS)))),
            "-F",
            ",".join(OUTPUT_TYPE_CODES),
        ]
        modules = selected_modules()
        usecase = selected_usecase()
        if modules:
            cmd.extend(["-m", ",".join(modules)])
        elif usecase:
            cmd.extend(["-u", usecase])
        else:
            cmd.extend(["-m", ",".join(DEFAULT_MODULES)])
        return cmd

    def _run_cli(self, target: str, script: Path) -> tuple[str, str, str | None]:
        """Run sf.py; always kill the process group on timeout (SF uses multiprocessing)."""
        cmd = self._build_command(target, script)
        timeout = self._cli_timeout()
        env = os.environ.copy()
        with tempfile.TemporaryDirectory(prefix="osint-sf-") as tmp:
            env["HOME"] = tmp
            env.setdefault("PYTHONUNBUFFERED", "1")
            proc = subprocess.Popen(
                cmd,
                cwd=str(script.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except Exception:
                    stdout, stderr = "", ""
                return stdout or "", "timeout", f"timeout after {int(timeout)}s"
            except Exception:
                _kill_group(proc)
                raise
        if proc.returncode not in (0, None) and not (stdout or "").strip():
            err = (stderr or "").strip() or f"exit {proc.returncode}"
            return stdout or "", "error", err[:500]
        return stdout or "", "ok", None


def _kill_group(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            return
