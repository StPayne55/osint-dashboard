# OSINT Desk

Self-hosted people-lookup dashboard that wraps **public, open-source OSINT tools** and free endpoints. Enter a name, email, phone, or username and get a live multi-module report: linked emails, social profiles, username candidates, phone metadata, Gravatar images, and search/dork links.

This is **not** a government records system and it does not query Spokeo, BeenVerified, Dehashed, or stolen credential dumps. Empty modules stay empty.

## Quick start (Docker)

```bash
docker compose up --build
```

Open [http://127.0.0.1:43145](http://127.0.0.1:43145). First load shows an ethical-use notice. Try `example@example.com`, `torvalds`, `+1 202 456 1111`, or `Ada Lovelace`.

No API keys are required. Optional keys (if you have them):

```bash
cp .env.example .env
# HIBP_API_KEY=...
# NUMVERIFY_API_KEY=...
# TWILIO_ACCOUNT_SID=...  TWILIO_AUTH_TOKEN=...   # optional US CNAM
docker compose up --build
```

Searches stay in memory and expire after an hour. Nothing sensitive is written to disk.

## Local development

Needs Python 3.12+ and Node 20+.

```bash
# backend
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cd backend && PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8742 --reload

# frontend (second terminal)
cd frontend
npm install
npm run dev
```

UI: [http://127.0.0.1:43145](http://127.0.0.1:43145) (Vite proxies `/api` to the backend).

```bash
cd backend && PYTHONPATH=. pytest
cd ../spiderfoot-runner && PYTHONPATH=. pytest
```

## What each module does

| Module | Tool | Accepts | What you get | Honest limits |
| --- | --- | --- | --- | --- |
| Username candidates | built-in | name, email, username | `firstlast`, email local-part, etc. | Guesses only |
| Email MX / disposable | dnspython | email | MX hosts, role/disposable hints | MX ≠ mailbox exists |
| Gravatar | public API | email | Avatar + published profile/accounts | Only if they opted in |
| Holehe | `holehe` | email | Sites that appear to have the email | Rate-limits look like misses |
| Socialscan | `socialscan` | email, username | Taken vs available on a small platform set | Few sites; no profile URLs |
| Sherlock | `sherlock-project` | username (or derived) | Profile URLs on a high-signal site subset. Tries 2–3 username candidates (undotted email locals first) | Soft-404 false positives possible. `SHERLOCK_FULL=1` for the complete list |
| Maigret | `maigret` (PyPI) | username (or derived) | Broader username dossier: profile URLs, tags, public display names / photos when parsing is on. Same multi-handle order as Sherlock | Default top-50 ranked sites, no Tor/.onion, disabled+NSFW sites skipped. `MAIGRET_FULL=1` for the complete enabled list. Soft-404s possible. Missing package → unavailable |
| SpiderFoot | SpiderFoot OSS CLI (not HX) | username, email, name, phone | Account/social profile URLs from a high-signal module set (Account Finder, Gravatar, Social, GitHub). Email queries seed the local-part handle (same order as Sherlock/Maigret — not digit-stripped) | **Off in the free web process.** Set `SPIDERFOOT_URL` + `SPIDERFOOT_RUNNER_TOKEN` to call the Starter runner, or `SPIDERFOOT_ENABLED=1` for a local `sf.py` fallback. Breach/dark-web modules are not enabled. Missing runner/binary → unavailable |
| Phone metadata | `phonenumbers` + `ignorant` | phone | E.164, country, carrier dataset, line type, site *registration* notes | Not CNAM / not an address. Ignorant hits are not profile URLs. PhoneInfoga binary is not bundled |
| theHarvester / CT | crt.sh + HackerTarget (+ CLI if present) | company email domain | Public hostnames / emails for that domain | Consumer mailboxes (Gmail, Yahoo, Outlook, …) are skipped — crt.sh noise is not people. Harvested addresses are filtered to the query / same local-part / company domain and capped |
| Search links / dorks | built-in | all | Google, DuckDuckGo, Bing, LinkedIn, plus labeled reverse-lookup links for phones | Links only; no scraping |
| HIBP | optional API | email | Breach titles | Skipped without `HIBP_API_KEY` |
| Numverify | optional API | phone | Carrier/line JSON | Skipped without `NUMVERIFY_API_KEY` |
| Twilio Lookup | optional API | phone | US CNAM caller name + line-type intelligence | Skipped without `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN`. Empty CNAM means no caller name on file (common for mobiles), never invented |

The in-app **Catalog** page repeats this list from the live backend (`GET /api/catalog`). AbstractAPI phone validation is implemented but **not registered** (disabled pending a key) so it does not appear in Catalog or live scan modules.

## SpiderFoot (open source, not HX)

SpiderFoot **v4.0** from [smicallef/spiderfoot](https://github.com/smicallef/spiderfoot) is the free OSS project. SpiderFoot HX and the heavy poppopjmp v6 microservices stack are not used.

**Recommended on Render:** a separate **Starter private runner** (`spiderfoot-runner`, ~$7/mo) so the free Desk web process never execs `sf.py`. Desk calls `POST /v1/scan` with `Authorization: Bearer <SPIDERFOOT_RUNNER_TOKEN>`. If `SPIDERFOOT_URL` is unset, Desk falls back to a local CLI only when `SPIDERFOOT_ENABLED=1` and `sf.py` is installed. **`SPIDERFOOT_URL` + token is enough to enable** — leave `SPIDERFOOT_ENABLED` off on the free web service.

Apply `render.yaml` (or [open the Blueprint](https://dashboard.render.com/blueprint/new?repo=https://github.com/StPayne55/osint-dashboard)):

1. Confirm **osint-dashboard** is the existing free Docker web service (`/api/health`).
2. Confirm **spiderfoot-runner** is `type: pserv`, plan `starter`, region `oregon`, Dockerfile `spiderfoot-runner/Dockerfile`.
3. The `spiderfoot-shared` env group generates `SPIDERFOOT_RUNNER_TOKEN` and attaches it to both services. Desk gets `SPIDERFOOT_URL` from the runner's internal `hostport` (`spiderfoot-runner:10000`; Desk prepends `http://`).
4. If Blueprint refuses `pserv` + Docker, deploy the same image as a Starter **web** service and set `SPIDERFOOT_URL` to that public URL. Token auth is still required; the runner does not expose `/docs`.
5. Skip the runner entirely and Desk stays free — Catalog shows SpiderFoot **unavailable**.

Local runner (optional):

```bash
# token must match on both services
export SPIDERFOOT_RUNNER_TOKEN=dev-runner-token
export SPIDERFOOT_URL=http://spiderfoot-runner:10000
docker compose --profile runner up --build
```

The runner image reuses `docker/install_spiderfoot.sh` + `docker/patch_spiderfoot.py` (Account Finder / WhatsMyName `wmn-data.json`, breach/dark-web modules removed). `GET /health` → `{ok:true, spiderfoot:true}`. Sync scans may take 2–5 minutes on Starter; Desk waits with a generous HTTP timeout. If the wall clock fires first, the runner aborts the scan and returns any ACCOUNT/SOCIAL events already stored in the temp SQLite DB (`status: timeout` with findings) instead of an empty timeout. **Deep / full-module scans are a future optional** (v1 stays on the social/account allowlist).

| Env | Default | Meaning |
| --- | --- | --- |
| `SPIDERFOOT_URL` | unset | Runner base URL (`http://spiderfoot-runner:10000` or `host:port`). Set this to enable remote mode |
| `SPIDERFOOT_RUNNER_TOKEN` | unset | Shared bearer secret (required with URL) |
| `SPIDERFOOT_ENABLED` | off (missing = off) | Local in-process `sf.py` only. Not required when URL+token are set |
| `SPIDERFOOT_TIMEOUT` | `75` local / `180` on Render web | Wall clock sent to the runner / local CLI. 120–180s on Starter is enough for partial ACCOUNT/SOCIAL hits; the runner salvages SQLite events on timeout |
| `SPIDERFOOT_MODULES` | `sfp_accounts,sfp_gravatar,sfp_social,sfp_github` | Comma-separated override. Default is the fast Starter set |
| `SPIDERFOOT_USECASE` | unset | Local CLI only: `passive` / `footprint` |
| `SPIDERFOOT_HOME` | `/opt/spiderfoot` | Local checkout for non-Docker / in-process fallback |
| `SPIDERFOOT_PYTHON` | `$SPIDERFOOT_HOME/.venv/bin/python` | Interpreter that has SF deps |
| `SPIDERFOOT_MAX_THREADS` | `8` on the runner / `2` local | `sf.py -max-threads`; Starter can run 8; keep 2 on a small local host |

The Desk image can still bundle SF (`docker build --build-arg INSTALL_SPIDERFOOT=0 .` skips it). Local (no Docker): clone OSS v4.0, create a venv, `pip install -r docker/spiderfoot-requirements.txt`, run `python3 docker/patch_spiderfoot.py /path/to/spiderfoot`, then set `SPIDERFOOT_HOME` and `SPIDERFOOT_ENABLED=1`.

**Maigret** is the official PyPI package (`pip install maigret`, already in `backend/requirements.txt`). It runs in-process via the Python API (not a sidecar): top-ranked sites only, no Tor proxy so `.onion` rows are skipped, disabled/NSFW tags dropped unless you opt in. `MAIGRET_TIMEOUT` (default 100s) is a hard wall clock. Default `MAIGRET_TOP_SITES=50` (override or set `MAIGRET_FULL=1`). `MAIGRET_PARSE=1` (default) fills public display names / photos into extras when the page exposes them.

## Render free tier

A single small instance cannot run Holehe, Socialscan, Sherlock, Maigret, and SpiderFoot at once — they starve each other (and even Gravatar) until every module times out. Defaults are tuned for that host. **Do not run `sf.py` inside the free web process.** Wire `SPIDERFOOT_URL` to the Starter runner, or leave SpiderFoot unavailable.

| Env | Default | Meaning |
| --- | --- | --- |
| `HEAVY_SCANNER_CONCURRENCY` | `1` | Shared slot for those five social crawlers. Set `2` on a larger box. |
| `SOCIAL_USERNAME_CANDIDATES` | `2` | Sherlock / Maigret / Socialscan handles to try (max 3). Undotted first when the email local-part has `.` or `+`. |
| `MAIGRET_TOP_SITES` | `50` | Ranked site slice. Raise toward 200+ if you have CPU to spare. |
| `MAIGRET_MAX_CONNECTIONS` | `10` | Concurrent Maigret HTTP connections |
| `SPIDERFOOT_URL` | unset | Enables remote runner (with token). Leave unset on free-only deploys |
| `SPIDERFOOT_ENABLED` | off | Local in-process CLI only; not needed when URL is set |
| `SPIDERFOOT_TIMEOUT` | `75` / `180` on Render | SF wall clock (120–180s recommended on Starter; partials are returned) |
| `SPIDERFOOT_MAX_THREADS` | `8` on the runner | `sf.py -max-threads`; override if the Starter box is tight |
| `SHERLOCK_FULL` | unset | Sherlock stays on the high-signal subset unless you set `1` |

Lightweight modules (username candidates, MX, Gravatar, dorks, Twilio, HIBP, …) still run in parallel. A heavy scanner stays **queued** on the module rail until it acquires the slot, then flips to **running**. Holehe and SpiderFoot keep any profile hits they already collected if the wall clock fires.

## Architecture

- FastAPI backend runs lightweight scanners in parallel and gates Holehe / Socialscan / Sherlock / Maigret / SpiderFoot with `HEAVY_SCANNER_CONCURRENCY`. Per-module timeouts start after a heavy scanner gets its slot. Progress is streamed over SSE (`GET /api/scans/{id}/events`).
- Optional `spiderfoot-runner` FastAPI service runs `sf.py` on a Starter private instance. Desk calls it over HTTP when `SPIDERFOOT_URL` is set.
- React + Vite dashboard (dark intel UI). Reports are assembled in memory.
- Each scanner implements a common `Scanner` interface (`backend/app/scanners/`). Missing tools degrade to `unavailable` instead of crashing the report.

## Smoke path

`example@example.com` should return structured sections without crashing: MX for `example.com`, a Gravatar hash (usually no avatar), Holehe site checks, generated username `example`, and a pack of dork links. A dotted Gmail local-part such as `Lisa.m.fraleigh@gmail.com` should list `lisamfraleigh` ahead of `lisa.m.fraleigh`, and Sherlock/Maigret/SpiderFoot should try the undotted handle first. An address like `stpayne55@gmail.com` must **not** invent `stpayne`. `torvalds` should return Sherlock and Maigret profile URLs when the network allows. SpiderFoot stays `unavailable` unless the runner URL+token are set (or `SPIDERFOOT_ENABLED=1` with a local `sf.py`). Missing `maigret` is the same: that module is `unavailable`, not a crash.

## UI

Cyberpunk desk: near-black field, cyan/magenta/acid-green neon, glass panels, CRT grain, blinking terminal cursor on search, and LED ticks on the live module rail. Ethical-use modal on first visit. Catalog lists every scanner. Run Lookup → a demo chip → watch SCANNING… complete.

## Ethics

Use this on your own data, with consent, or for authorized investigations. Do not stalk, harass, or doxx private people.
