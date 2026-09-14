from __future__ import annotations

import os


APP_NAME = "OSINT Desk"
APP_VERSION = "1.0.0"

API_HOST = os.getenv("OSINT_HOST", "0.0.0.0")
API_PORT = int(os.getenv("OSINT_PORT", "8742"))


def _int_env(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        value = default
    else:
        try:
            value = max(minimum, int(raw))
        except ValueError:
            value = default
    if maximum is not None:
        return min(maximum, value)
    return value


def env_flag(name: str, default: bool = False) -> bool:
    """Opt-in boolean. Missing or blank uses *default*; only 1/true/yes/on enable."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Per-scanner wall clocks. One hung tool must not block the report.
DEFAULT_TIMEOUT = float(os.getenv("SCANNER_TIMEOUT", "45"))
HOLEHE_TIMEOUT = float(os.getenv("HOLEHE_TIMEOUT", "75"))
SHERLOCK_TIMEOUT = float(os.getenv("SHERLOCK_TIMEOUT", "90"))
SOCIALSCAN_TIMEOUT = float(os.getenv("SOCIALSCAN_TIMEOUT", "40"))
HARVESTER_TIMEOUT = float(os.getenv("HARVESTER_TIMEOUT", "45"))
PHONE_TIMEOUT = float(os.getenv("PHONE_TIMEOUT", "30"))
# Shared slot for Holehe / Socialscan / Sherlock / Maigret / SpiderFoot so a
# single small host (Render free) is not starved by five parallel site crawls.
# Lightweight modules (Gravatar, MX, dorks, Twilio, …) stay ungated.
HEAVY_SCANNER_CONCURRENCY = _int_env("HEAVY_SCANNER_CONCURRENCY", 1)
# Sherlock / Maigret / Socialscan try this many derived handles (2–3).
# Prefer undotted local-parts first when the email contains . or +.
SOCIAL_USERNAME_CANDIDATES = _int_env("SOCIAL_USERNAME_CANDIDATES", 2, minimum=1, maximum=3)
# SpiderFoot OSS is slow and regularly hits the wall clock on Render free.
# Local in-process CLI is off unless SPIDERFOOT_ENABLED=1.
# Remote runner: SPIDERFOOT_URL + SPIDERFOOT_RUNNER_TOKEN is enough to enable
# (do not also set SPIDERFOOT_ENABLED on the free web service).
SPIDERFOOT_TIMEOUT = float(os.getenv("SPIDERFOOT_TIMEOUT", "75"))
SPIDERFOOT_ENABLED = env_flag("SPIDERFOOT_ENABLED", default=False)
SPIDERFOOT_URL = os.getenv("SPIDERFOOT_URL", "").strip()
SPIDERFOOT_RUNNER_TOKEN = os.getenv("SPIDERFOOT_RUNNER_TOKEN", "").strip()
SPIDERFOOT_HOME = os.getenv("SPIDERFOOT_HOME", "/opt/spiderfoot").strip() or "/opt/spiderfoot"
SPIDERFOOT_USECASE = os.getenv("SPIDERFOOT_USECASE", "").strip().lower()
SPIDERFOOT_MODULES = os.getenv("SPIDERFOOT_MODULES", "").strip()
# Keep this low on small hosts (Render free): SF uses multiprocessing.
SPIDERFOOT_MAX_THREADS = int(os.getenv("SPIDERFOOT_MAX_THREADS", "2"))
# HTTP wait when Desk calls the runner. Starter can hold a 2–5 min scan.
SPIDERFOOT_REMOTE_TIMEOUT = float(os.getenv("SPIDERFOOT_REMOTE_TIMEOUT", "240"))

# Sherlock checks 400+ sites by default; the dashboard uses a high-signal
# subset unless SHERLOCK_FULL=1.
SHERLOCK_FULL = os.getenv("SHERLOCK_FULL", "").lower() in {"1", "true", "yes"}
SHERLOCK_SITE_TIMEOUT = float(os.getenv("SHERLOCK_SITE_TIMEOUT", "8"))

# Maigret default is top-500; keep a smaller slice so Render stays responsive.
MAIGRET_TIMEOUT = float(os.getenv("MAIGRET_TIMEOUT", "100"))
MAIGRET_SITE_TIMEOUT = float(os.getenv("MAIGRET_SITE_TIMEOUT", "8"))
MAIGRET_TOP_SITES = _int_env("MAIGRET_TOP_SITES", 50, minimum=1)
MAIGRET_MAX_CONNECTIONS = _int_env("MAIGRET_MAX_CONNECTIONS", 10)
MAIGRET_FULL = os.getenv("MAIGRET_FULL", "").lower() in {"1", "true", "yes"}
MAIGRET_NSFW = os.getenv("MAIGRET_NSFW", "").lower() in {"1", "true", "yes"}
MAIGRET_PARSE = os.getenv("MAIGRET_PARSE", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# Optional paid/key APIs — skipped when unset.
HIBP_API_KEY = os.getenv("HIBP_API_KEY", "").strip()
NUMVERIFY_API_KEY = os.getenv("NUMVERIFY_API_KEY", "").strip()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
ABSTRACT_PHONE_API_KEY = os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()
PDL_API_KEY = os.getenv("PDL_API_KEY", "").strip()
WHITEPAGES_API_KEY = os.getenv("WHITEPAGES_API_KEY", "").strip()
TRESTLE_API_KEY = os.getenv("TRESTLE_API_KEY", "").strip()

# Rate limit: scans per window per client IP.
RATE_LIMIT_SCANS = int(os.getenv("RATE_LIMIT_SCANS", "12"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "600"))

JOB_TTL_SEC = int(os.getenv("JOB_TTL_SEC", "3600"))
MAX_JOBS = int(os.getenv("MAX_JOBS", "80"))

# Persistence is off. Set PERSIST_SEARCHES=1 only for local debugging.
PERSIST_SEARCHES = os.getenv("PERSIST_SEARCHES", "").lower() in {"1", "true", "yes"}

USER_AGENT = (
    "OSINT-Desk/1.0 (+https://localhost; self-hosted public-source lookup)"
)
