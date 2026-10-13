# BeforeYouGo

Event intelligence and accountability platform (Discover → Decide → Verify → Improve).
FastAPI + SQLAlchemy + PostgreSQL backend, React + TypeScript + Vite frontend (served by the backend after `npm run build`).

## Run
```
cp .env.example .env            # set SECRET_KEY; DATABASE_URL must point at PostgreSQL 16 (pg_trgm available)
cd backend && python -m venv .venv && .venv/bin/pip install -e . 2>/dev/null || true   # see pyproject / installed deps
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli sync                 # pull real events from connected sources
.venv/bin/python -m app.cli create-admin --email you@yourdomain.dev
cd ../frontend && npm install && npm run build
cd ../backend && .venv/bin/uvicorn app.main:app --port 8001   # http://127.0.0.1:8001, API docs at /api/docs
```
`scripts/dev.sh start|stop` wraps migrate, build and serve. Health: `/api/health`, readiness: `/api/ready`.

## Test
```
cd backend && BYG_ENV=test .venv/bin/python -m pytest        # 168 tests, uses database beforeyougo_test
cd frontend && npm test                                      # 34 unit tests
cd frontend && BASE_URL=http://127.0.0.1:8001 npm run e2e    # Playwright flows (set ADMIN_EMAIL/ADMIN_PASSWORD for admin)
```

## Connected sources (honest status)
| Source | Status |
|---|---|
| tech-conferences/conference-data (GitHub) | Working, verified live (540 records) |
| developers.events calendar (GitHub) | Working, verified live (1,064 records) |
| ICS feeds | Implemented; needs `ICS_FEED_URLS` |
| Organizer/user-submitted event pages and text | Implemented (SSRF-safe fetcher) |
| MLH, Devfolio, Unstop, Eventbrite, Meetup, HackerEarth, Townscript | **Not integrated.** The build sandbox blocked outbound access (HTTP 403 at the proxy), so access could not be verified, and no connector was faked. They appear in the source catalogue as not integrated. |

## Known limitations
- The live data is mostly conferences, with few Indian student hackathons, until Indian platform connectors or ICS feeds are added from an environment with network access. Most records do not state fees, so they show "Not stated" and budget filters are conservative.
- No LLM key was configured here; the analyzer ran on its deterministic fallback (the UI labels this). The LLM path is covered only by mocked tests.
- Rate limiter and scheduler are in-process (single node). No Celery/Redis, pgvector or semantic search yet; search is Postgres full-text + trigram.
- `mypy app` still reports ~30 type errors (none block runtime); ruff is clean.
- The CLI `create-admin` does not validate email format like the API does.
- Not tested: real browser against a deployed host, load, and any LLM provider.
