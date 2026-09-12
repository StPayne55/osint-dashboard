"""SpiderFoot OSS CLI helpers for the dedicated runner (not HX)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Keep in sync with backend/app/scanners/spiderfoot_scan.py
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

OUTPUT_TYPE_CODES = (
    "ACCOUNT_EXTERNAL_OWNED",
    "SIMILAR_ACCOUNT_EXTERNAL",
    "SOCIAL_MEDIA",
    "USERNAME",
    "EMAILADDR",
    "HUMAN_NAME",
    "PHONE_NUMBER",
)

# Same set docker/patch_spiderfoot.py deletes from the image.
BLOCKED_MODULES = {
    "sfp_haveibeenpwned",
    "sfp_dehashed",
    "sfp_ahmia",
    "sfp_onioncity",
    "sfp_onionsearchengine",
    "sfp_torch",
    "sfp_leakix",
    "sfp_intelx",
    "sfp_psbdmp",
    "sfp_pastebin",
    "sfp_sociallinks",
    "sfp_breachdirectory",
    "sfp_leaklookup",
}


def sf_home() -> Path:
    return Path(os.getenv("SPIDERFOOT_HOME", "/opt/spiderfoot") or "/opt/spiderfoot")


def sf_script_path() -> Path | None:
    script = sf_home() / "sf.py"
    return script if script.is_file() else None


def sf_python() -> str:
    explicit = os.getenv("SPIDERFOOT_PYTHON", "").strip()
    if explicit:
        return explicit
    venv = sf_home() / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    return sys.executable


def sanitize_modules(modules: list[str] | None) -> list[str]:
    """Allowlist social/account modules; drop breach/dark-web names."""
    requested = [part.strip() for part in (modules or []) if part and part.strip()]
    cleaned: list[str] = []
    for name in requested:
        if not name.startswith("sfp_"):
            continue
        if name in BLOCKED_MODULES:
            continue
        if name not in cleaned:
            cleaned.append(name)
    return cleaned or list(DEFAULT_MODULES)


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


def stdout_excerpt(stdout: str, limit: int = 2000) -> str:
    text = stdout or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_command(target: str, script: Path, modules: list[str]) -> list[str]:
    threads = max(1, int(os.getenv("SPIDERFOOT_MAX_THREADS", "2")))
    return [
        sf_python(),
        str(script),
        "-s",
        target,
        "-o",
        "json",
        "-q",
        "-n",
        "-max-threads",
        str(threads),
        "-F",
        ",".join(OUTPUT_TYPE_CODES),
        "-m",
        ",".join(modules),
    ]


def run_spiderfoot(target: str, modules: list[str] | None = None, timeout: int = 180) -> dict[str, Any]:
    """Run sf.py off the caller thread. Always kill the process group on timeout."""
    script = sf_script_path()
    if script is None:
        return {
            "status": "error",
            "target": target,
            "events": [],
            "stdout_excerpt": "",
            "error": f"sf.py not found under {sf_home()}",
        }
    chosen = sanitize_modules(modules)
    wall = max(10, int(timeout))
    cmd = build_command(target, script, chosen)
    env = os.environ.copy()
    stdout = ""
    stderr = ""
    status = "ok"
    error: str | None = None
    with tempfile.TemporaryDirectory(prefix="sf-runner-") as tmp:
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
            stdout, stderr = proc.communicate(timeout=wall)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", ""
            status = "timeout"
            error = f"timeout after {wall}s"
        except Exception as exc:
            _kill_group(proc)
            return {
                "status": "error",
                "target": target,
                "events": [],
                "stdout_excerpt": "",
                "error": str(exc)[:500],
            }
    if status == "ok" and proc.returncode not in (0, None) and not (stdout or "").strip():
        status = "error"
        error = ((stderr or "").strip() or f"exit {proc.returncode}")[:500]
    events = parse_spiderfoot_stdout(stdout or "")
    return {
        "status": status,
        "target": target,
        "events": events,
        "stdout_excerpt": stdout_excerpt(stdout or ""),
        "error": error,
    }


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
