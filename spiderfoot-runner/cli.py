"""SpiderFoot OSS CLI helpers for the dedicated runner (not HX)."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from salvage import merge_events, salvage_scan_events

log = logging.getLogger("spiderfoot-runner")

# Keep in sync with backend/app/scanners/spiderfoot_scan.py
# High-signal set for Starter (~180–240s). Override via request modules /
# Desk SPIDERFOOT_MODULES. Breach/dark-web names are still blocked below.
DEFAULT_MODULES = (
    "sfp_accounts",
    "sfp_gravatar",
    "sfp_social",
    "sfp_github",
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


def stderr_excerpt(stderr: str, limit: int = 2000) -> str:
    return stdout_excerpt(stderr, limit=limit)


def max_threads() -> int:
    raw = (os.getenv("SPIDERFOOT_MAX_THREADS") or "8").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


def abort_grace_seconds() -> float:
    raw = (os.getenv("SPIDERFOOT_ABORT_GRACE") or "4").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 4.0


def persistent_cache_dir() -> Path:
    """Keep WhatsMyName + distrust cache outside the per-scan temp HOME.

    Each scan isolates SPIDERFOOT_DATA (the SQLite DB) under a TemporaryDirectory.
    Without SPIDERFOOT_CACHE, v4 also stores cacheGet/cachePut there, so every
    request is a cold 715-site distrust sweep. A stable cache dir next to
    sf.py survives for the life of the Starter instance.
    """
    raw = (os.getenv("SPIDERFOOT_CACHE") or "").strip()
    path = Path(raw) if raw else (sf_home() / "cache")
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_scan_env(env: dict[str, str]) -> dict[str, str]:
    """Apply Account Finder knobs and a persistent cache for this sf.py child."""
    env.setdefault("SPIDERFOOT_SKIP_DISTRUST", "1")
    env.setdefault("SPIDERFOOT_ACCOUNTS_MAX_SITES", "120")
    cache = persistent_cache_dir()
    env["SPIDERFOOT_CACHE"] = str(cache)
    bundled = sf_home() / "data" / "wmn-data.json"
    priority = sf_home() / "data" / "wmn-priority.json"
    if bundled.is_file():
        env.setdefault("SPIDERFOOT_WMN_JSON", str(bundled))
    elif priority.is_file():
        env.setdefault("SPIDERFOOT_WMN_JSON", str(priority))
    # Pre-bake empty distrust state so an accidental skip-off still
    # does not re-sweep 715 sites on a cold cache.
    try:
        sys.path.insert(0, str(sf_home()))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker"))
        from accounts_tune import bake_spiderfoot_cache

        bake_spiderfoot_cache(cache)
    except Exception as exc:
        log.debug("Could not pre-bake SpiderFoot cache: %s", exc)
    return env


def build_command(target: str, script: Path, modules: list[str]) -> list[str]:
    threads = max_threads()
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
    """Run sf.py off the caller thread. On timeout, salvage events from SQLite."""
    script = sf_script_path()
    if script is None:
        return _payload(
            "error",
            target,
            [],
            error=f"sf.py not found under {sf_home()}",
        )
    chosen = sanitize_modules(modules)
    wall = max(10, int(timeout))
    cmd = build_command(target, script, chosen)
    env = os.environ.copy()
    stdout = ""
    stderr = ""
    status = "ok"
    error: str | None = None
    salvaged: list[dict[str, Any]] = []
    scan_id: str | None = None
    with tempfile.TemporaryDirectory(prefix="sf-runner-") as tmp:
        data_dir = Path(tmp) / ".spiderfoot"
        data_dir.mkdir(parents=True, exist_ok=True)
        env["HOME"] = tmp
        # Isolate the scan DB so we can find it after a timeout. sf.py v4.0
        # writes {SPIDERFOOT_DATA or $HOME/.spiderfoot}/spiderfoot.db.
        env["SPIDERFOOT_DATA"] = str(data_dir)
        seed_scan_env(env)
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
            stdout, stderr = _graceful_abort(proc)
            status = "timeout"
            error = f"timeout after {wall}s"
            salvaged, scan_id = salvage_scan_events(data_dir, tmp, target=target)
        except Exception as exc:
            _kill_group(proc)
            err_text = str(exc)[:500]
            log.warning("sf.py error for %s: %s", target, err_text)
            return _payload("error", target, [], error=err_text)
        if status == "ok" and proc.returncode not in (0, None) and not (stdout or "").strip():
            status = "error"
            error = ((stderr or "").strip() or f"exit {proc.returncode}")[:500]
            salvaged, scan_id = salvage_scan_events(data_dir, tmp, target=target)
        events = merge_events(parse_spiderfoot_stdout(stdout or ""), salvaged)
        if salvaged:
            log.info(
                "salvaged event types for %s: %s",
                target,
                format_event_type_counts(event_type_counts(salvaged)),
            )
        if status in {"timeout", "error"}:
            _log_failure(status, target, stderr, events)
        return _payload(
            status,
            target,
            events,
            stdout=stdout,
            stderr=stderr,
            error=error,
            scan_id=scan_id,
            salvaged=bool(salvaged),
        )


def _payload(
    status: str,
    target: str,
    events: list[dict[str, Any]],
    *,
    stdout: str = "",
    stderr: str = "",
    error: str | None = None,
    scan_id: str | None = None,
    salvaged: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "target": target,
        "events": events,
        "stdout_excerpt": stdout_excerpt(stdout or ""),
        "stderr_excerpt": stderr_excerpt(stderr or ""),
        "error": error,
        "scan_id": scan_id,
        "salvaged": salvaged,
    }


def event_type_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        key = str(event.get("type") or event.get("eventType") or "?") or "?"
        counts[key] = counts.get(key, 0) + 1
    return counts


def format_event_type_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))


def _log_failure(status: str, target: str, stderr: str, events: list[dict[str, Any]]) -> None:
    excerpt = stderr_excerpt(stderr or "")
    log.warning(
        "sf.py %s for %s (%s event(s); %s) stderr: %s",
        status,
        target,
        len(events),
        format_event_type_counts(event_type_counts(events)),
        excerpt or "(empty)",
    )


def _signal_group(proc: subprocess.Popen[str], sig: int) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.send_signal(sig)
        except Exception:
            return


def _graceful_abort(proc: subprocess.Popen[str], grace: float | None = None) -> tuple[str, str]:
    """SIGINT so sf.py handle_abort marks ABORTED, then SIGTERM, then SIGKILL."""
    wait = abort_grace_seconds() if grace is None else max(1.0, float(grace))
    _signal_group(proc, signal.SIGINT)
    try:
        return proc.communicate(timeout=wait)
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    _signal_group(proc, signal.SIGTERM)
    try:
        return proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    _kill_group(proc)
    try:
        return proc.communicate(timeout=3)
    except Exception:
        return "", ""


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
