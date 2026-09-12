from __future__ import annotations

import os


APP_NAME = "OSINT Desk"
APP_VERSION = "1.0.0"

API_HOST = os.getenv("OSINT_HOST", "0.0.0.0")
API_PORT = int(os.getenv("OSINT_PORT", "8742"))

# Per-scanner wall clocks. One hung tool must not block the report.
DEFAULT_TIMEOUT = float(os.getenv("SCANNER_TIMEOUT", "45"))
HOLEHE_TIMEOUT = float(os.getenv("HOLEHE_TIMEOUT", "75"))
SHERLOCK_TIMEOUT = float(os.getenv("SHERLOCK_TIMEOUT", "90"))
SOCIALSCAN_TIMEOUT = float(os.getenv("SOCIALSCAN_TIMEOUT", "40"))
HARVESTER_TIMEOUT = float(os.getenv("HARVESTER_TIMEOUT", "45"))
PHONE_TIMEOUT = float(os.getenv("PHONE_TIMEOUT", "30"))
# SpiderFoot OSS is slow; keep a hard wall clock so one scan cannot stall Render.
SPIDERFOOT_TIMEOUT = float(os.getenv("SPIDERFOOT_TIMEOUT", "120"))
SPIDERFOOT_ENABLED = os.getenv("SPIDERFOOT_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
SPIDERFOOT_HOME = os.getenv("SPIDERFOOT_HOME", "/opt/spiderfoot").strip() or "/opt/spiderfoot"
SPIDERFOOT_USECASE = os.getenv("SPIDERFOOT_USECASE", "").strip().lower()
SPIDERFOOT_MODULES = os.getenv("SPIDERFOOT_MODULES", "").strip()
SPIDERFOOT_MAX_THREADS = int(os.getenv("SPIDERFOOT_MAX_THREADS", "3"))

# Sherlock checks 400+ sites by default; the dashboard uses a high-signal
# subset unless SHERLOCK_FULL=1.
SHERLOCK_FULL = os.getenv("SHERLOCK_FULL", "").lower() in {"1", "true", "yes"}
SHERLOCK_SITE_TIMEOUT = float(os.getenv("SHERLOCK_SITE_TIMEOUT", "8"))

# Optional paid/key APIs — skipped when unset.
HIBP_API_KEY = os.getenv("HIBP_API_KEY", "").strip()
NUMVERIFY_API_KEY = os.getenv("NUMVERIFY_API_KEY", "").strip()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
ABSTRACT_PHONE_API_KEY = os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()

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
