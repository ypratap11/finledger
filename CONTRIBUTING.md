# Contributing to FinLedger

Thanks for your interest. FinLedger is Apache-2.0 licensed and open to contributions.

## Quick start

Prerequisites: Docker, Python 3.12+, Node 20+.

```bash
git clone https://github.com/ypratap11/finledger.git
cd finledger

# Start Postgres
docker compose up -d postgres

# Python core
cd core
python -m venv .venv
.venv/Scripts/pip install -e '.[dev]'    # Windows
# source .venv/bin/activate && pip install -e '.[dev]'   # macOS/Linux
.venv/Scripts/alembic upgrade head
.venv/Scripts/python seed_demo.py
.venv/Scripts/uvicorn finledger.ui.app:app --port 8003

# In another shell: Node ingest-edge
cd ingest-edge
npm install
STRIPE_WEBHOOK_SECRET=whsec_test npm run dev
```

Open http://localhost:8003/ for the dashboard.

## Running tests

```bash
cd core
.venv/Scripts/pytest tests/                # full suite
.venv/Scripts/pytest tests/unit             # fast
.venv/Scripts/pytest tests/integration      # needs Postgres
.venv/Scripts/pytest tests/property         # Hypothesis, slow

cd ingest-edge
npm test                                    # vitest
```

Targets before submitting a PR: all tests green, `ruff check src tests` clean.

## Project layout

```
core/              Python: FastAPI UI, posting engine, revrec, migrations
ingest-edge/       Node/TS: Stripe + Zuora webhook edge with signature verification
docs/superpowers/  Design specs, implementation plans, task RFCs
fixtures/          Sample webhook payloads
```

The `docs/superpowers/specs/` directory is the best place to understand the *why* behind the architecture. Start with `2026-04-14-finledger-design.md`.

## How to contribute

1. **Open an issue first** for anything non-trivial. We'd rather discuss the design than review code written for the wrong problem.
2. **Keep PRs focused.** One feature or fix per PR. Follow the existing commit style (`feat(scope): ...`, `fix(scope): ...`, `test(scope): ...`, `docs: ...`).
3. **Add tests.** New pattern? Unit tests. New endpoint? Integration tests. New invariant? Hypothesis property test.
4. **No scope creep.** Spotted something unrelated? Open a separate issue.

### Code style

- Python: Ruff-formatted, type hints on public APIs, sync psycopg for UI routes and async asyncpg for engine/tests (there's a known Windows asyncpg bug — see `core/src/finledger/db.py`).
- TypeScript: `npx tsc --noEmit` clean, `vitest run` green.
- Migrations: one table per migration, chained revisions, named CHECK constraints (`ck_<table>_<rule>`), named indexes (`ix_<table>_<col>`).

## Good first issues

Look for issues tagged `good-first-issue` on GitHub.

Likely early-contribution areas:
- Additional source adapters (Chargebee, Recurly, Paddle, Maxio)
- Additional GL exporters (NetSuite SuiteTalk, SAP FBDI, Oracle FBDI)
- Translation / i18n for UI
- Accessibility audit on dashboard pages

## Roadmap

See the `## What's next` section in the README and the specs in `docs/superpowers/specs/`. Upcoming:

- **M2a-1.5** — consumption-based recognition (usage events pipeline)
- **M2a-2** — SSP allocation + contract modifications
- **M2a-3** — variable consideration + constraint
- **M2b** — real Zuora sandbox integration + Zuora↔Ledger recon
- **M2c** — first real ERP connector

## Reporting security issues

Please **don't** open a public issue for security vulnerabilities. Email the maintainers directly (see repo profile) or use GitHub's private vulnerability reporting.

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0, same as the project.
