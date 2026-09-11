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
| Phone metadata | `phonenumbers` + `ignorant` | phone | E.164, country, carrier dataset, line type, a few site checks | Not CNAM / not an address. PhoneInfoga binary is not bundled |
| theHarvester / CT | crt.sh + HackerTarget (+ CLI if present) | email domain | Public hostnames / emails for that domain | Name-only queries are skipped — use dorks. Current theHarvester git needs Python 3.14; PyPI `0.0.1` is a stub |
| Search links / dorks | built-in | all | Google, DuckDuckGo, Bing, LinkedIn, Facebook, Whitepages-style queries | Links only; no scraping |
| HIBP | optional API | email | Breach titles | Skipped without `HIBP_API_KEY` |
| Numverify | optional API | phone | Carrier/line JSON | Skipped without `NUMVERIFY_API_KEY` |

The in-app **Catalog** page repeats this list from the live backend (`GET /api/catalog`).

## Architecture

- FastAPI backend runs scanners in parallel with per-module timeouts. Progress is streamed over SSE (`GET /api/scans/{id}/events`).
- React + Vite dashboard (dark intel UI). Reports are assembled in memory.
- Each scanner implements a common `Scanner` interface (`backend/app/scanners/`). Missing tools degrade to `unavailable` instead of crashing the report.

## Smoke path

`example@example.com` should return structured sections without crashing: MX for `example.com`, a Gravatar hash (usually no avatar), Holehe site checks, generated username `example`, and a pack of dork links. `torvalds` should return Sherlock profile URLs when the network allows.

## UI

Cyberpunk desk: near-black field, cyan/magenta/acid-green neon, glass panels, CRT grain, blinking terminal cursor on search, and LED ticks on the live module rail. Ethical-use modal on first visit. Catalog lists every scanner. Run Lookup → a demo chip → watch SCANNING… complete.

## Ethics

Use this on your own data, with consent, or for authorized investigations. Do not stalk, harass, or doxx private people.
