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
```

## What each module does

| Module | Tool | Accepts | What you get | Honest limits |
| --- | --- | --- | --- | --- |
| Username candidates | built-in | name, email, username | `firstlast`, email local-part, etc. | Guesses only |
| Email MX / disposable | dnspython | email | MX hosts, role/disposable hints | MX ≠ mailbox exists |
| Gravatar | public API | email | Avatar + published profile/accounts | Only if they opted in |
| Holehe | `holehe` | email | Sites that appear to have the email | Rate-limits look like misses |
| Socialscan | `socialscan` | email, username | Taken vs available on a small platform set | Few sites; no profile URLs |
| Sherlock | `sherlock-project` | username (or derived) | Profile URLs on a high-signal site subset | Soft-404 false positives possible. `SHERLOCK_FULL=1` for the complete list |
| Maigret | `maigret` (PyPI) | username (or derived) | Broader username dossier: profile URLs, tags, public display names / photos when parsing is on | Default top-200 ranked sites, no Tor/.onion, disabled+NSFW sites skipped. `MAIGRET_FULL=1` for the complete enabled list. Soft-404s possible. Missing package → unavailable |
| SpiderFoot | SpiderFoot OSS CLI (not HX) | username, email, name, phone | Account/social profile URLs from a limited module set (Account Finder, GitHub, Twitter, …) | Hard timeout (default 120s). Breach/dark-web modules are not enabled. Dictionary-word usernames are skipped. Missing `sf.py` → unavailable |
| Phone metadata | `phonenumbers` + `ignorant` | phone | E.164, country, carrier dataset, line type, site *registration* notes | Not CNAM / not an address. Ignorant hits are not profile URLs. PhoneInfoga binary is not bundled |
| theHarvester / CT | crt.sh + HackerTarget (+ CLI if present) | company email domain | Public hostnames / emails for that domain | Consumer mailboxes (Gmail, Yahoo, Outlook, …) are skipped — crt.sh noise is not people. Harvested addresses are filtered to the query / same local-part / company domain and capped |
| Search links / dorks | built-in | all | Google, DuckDuckGo, Bing, LinkedIn, plus labeled reverse-lookup links for phones | Links only; no scraping |
| HIBP | optional API | email | Breach titles | Skipped without `HIBP_API_KEY` |
| Numverify | optional API | phone | Carrier/line JSON | Skipped without `NUMVERIFY_API_KEY` |
| Twilio Lookup | optional API | phone | US CNAM caller name + line-type intelligence | Skipped without `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN`. Empty CNAM means no caller name on file (common for mobiles), never invented |

The in-app **Catalog** page repeats this list from the live backend (`GET /api/catalog`). AbstractAPI phone validation is implemented but **not registered** (disabled pending a key) so it does not appear in Catalog or live scan modules.

## SpiderFoot (open source, not HX)

The Docker image clones SpiderFoot **v4.0** from [smicallef/spiderfoot](https://github.com/smicallef/spiderfoot) into `/opt/spiderfoot` and installs its requirements in **`/opt/spiderfoot/.venv`** so CherryPy/lxml pins cannot break FastAPI. This is the free OSS project. SpiderFoot HX (the commercial cloud product) is not used and is not a dependency.

**Size tradeoff:** the isolated venv and 200+ modules add roughly **200–400 MB** to the image. Worth it for account/social URL coverage that Sherlock/Holehe/Socialscan miss. Skip the bundle with `docker build --build-arg INSTALL_SPIDERFOOT=0 .` (the scanner then reports `unavailable`).

Scans run **in-process via the CLI** (`sf.py -s … -o json -q`) inside the same Render web service — no SpiderFoot sidecar or extra port. The CLI is launched with `asyncio.to_thread` so `Popen.communicate` cannot freeze uvicorn (health, `GET /api/scans/{id}`, and SSE stay responsive). A hard timeout (`SPIDERFOOT_TIMEOUT`, default 120s) kills the process group so one hung scan cannot stall the job. Default modules are an account/social allowlist (`sfp_accounts`, GitHub, Twitter, Instagram, Gravatar, Keybase, …). Breach, dump, and dark-web modules are stripped from the image and never selected.

| Env | Default | Meaning |
| --- | --- | --- |
| `SPIDERFOOT_ENABLED` | `1` if `sf.py` is present | Set `0` to hide the scanner |
| `SPIDERFOOT_TIMEOUT` | `120` | Wall clock; CLI is killed ~5s earlier |
| `SPIDERFOOT_MODULES` | social/account allowlist | Comma-separated override |
| `SPIDERFOOT_USECASE` | unset | `passive` / `footprint` only if you want a broader set |
| `SPIDERFOOT_HOME` | `/opt/spiderfoot` | Local checkout for non-Docker dev |
| `SPIDERFOOT_PYTHON` | `$SPIDERFOOT_HOME/.venv/bin/python` | Interpreter that has SF deps |
| `SPIDERFOOT_MAX_THREADS` | `2` | `sf.py -max-threads`; keep low on small Render hosts |

Local (no Docker): clone OSS v4.0, create a venv, `pip install -r docker/spiderfoot-requirements.txt`, run `python3 docker/patch_spiderfoot.py /path/to/spiderfoot` so Account Finder can read current WhatsMyName `wmn-data.json`, then set `SPIDERFOOT_HOME`.

**Maigret** is the official PyPI package (`pip install maigret`, already in `backend/requirements.txt`). It runs in-process via the Python API (not a sidecar): top-ranked sites only, no Tor proxy so `.onion` rows are skipped, disabled/NSFW tags dropped unless you opt in. `MAIGRET_TIMEOUT` (default 100s) is a hard wall clock. `MAIGRET_PARSE=1` (default) fills public display names / photos into extras when the page exposes them.

## Architecture

- FastAPI backend runs scanners in parallel with per-module timeouts. Progress is streamed over SSE (`GET /api/scans/{id}/events`).
- React + Vite dashboard (dark intel UI). Reports are assembled in memory.
- Each scanner implements a common `Scanner` interface (`backend/app/scanners/`). Missing tools degrade to `unavailable` instead of crashing the report.

## Smoke path

`example@example.com` should return structured sections without crashing: MX for `example.com`, a Gravatar hash (usually no avatar), Holehe site checks, generated username `example`, and a pack of dork links. `torvalds` should return Sherlock, Maigret, and (when bundled) SpiderFoot profile URLs when the network allows. Without `/opt/spiderfoot/sf.py`, SpiderFoot stays `unavailable` and the rest of the report still completes. Missing `maigret` is the same: that module is `unavailable`, not a crash.

## UI

Cyberpunk desk: near-black field, cyan/magenta/acid-green neon, glass panels, CRT grain, blinking terminal cursor on search, and LED ticks on the live module rail. Ethical-use modal on first visit. Catalog lists every scanner. Run Lookup → a demo chip → watch SCANNING… complete.

## Ethics

Use this on your own data, with consent, or for authorized investigations. Do not stalk, harass, or doxx private people.
