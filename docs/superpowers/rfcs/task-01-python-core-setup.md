# Task 1 RFC — Python Core Project Setup

**Plan reference:** `docs/superpowers/plans/2026-04-14-finledger-m1.md` Task 1.

**What this task delivers:** A Python package under `core/` that is `pip install -e`-able, with Alembic wired up and ready to run migrations against Postgres (though no migrations exist yet). After it, `alembic history` succeeds and the `finledger.config.settings` object can be imported from a REPL.

**Why this task exists:** Every subsequent Python task imports `from finledger.<module> import ...`. That requires a package layout + install. Alembic needs its own config wiring to know where `versions/` lives and how to read the DB URL from env. Doing both together is one logical unit: "the Python side is ready to build on."

---

## File 1: `core/pyproject.toml`

### Package metadata section
```toml
[project]
name = "finledger"
version = "0.1.0"
requires-python = ">=3.12"
```

| Line | Reason |
|------|--------|
| `name = "finledger"` | The importable package name. Must match the directory under `src/` (`src/finledger/`). |
| `version = "0.1.0"` | Semver start. Portfolio project so version is more cosmetic than functional, but setting it correctly makes the project look real. |
| `requires-python = ">=3.12"` | 3.12 is current as of 2026-04; we use 3.12 features (PEP 695 generics, improved error messages, faster asyncio). Pinning the minimum means `pip install` fails fast on old Pythons rather than producing confusing errors later. |

### Runtime dependencies
```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlalchemy>=2.0",
  "asyncpg>=0.30",
  "psycopg[binary]>=3.2",
  "alembic>=1.14",
  "apscheduler>=3.10",
  "jinja2>=3.1",
  "stripe>=11.0",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "httpx>=0.27",
]
```

| Dep | Why |
|-----|-----|
| `fastapi>=0.115` | The admin UI + future API. 0.115 has the `TemplateResponse(request=..., name=...)` signature we use in Task 25; earlier versions had a different signature. |
| `uvicorn[standard]` | ASGI server for FastAPI. The `[standard]` extra includes `httptools` (faster parsing) and `websockets` (not needed now but adds no weight). |
| `sqlalchemy>=2.0` | The 2.0-style API (`Mapped`, `select(...)`, `async_sessionmaker`) is the one we use in the models. 1.x-style syntax would not work with our code. |
| `asyncpg>=0.30` | Native async Postgres driver. SQLAlchemy 2.0 runs on top of it via `postgresql+asyncpg://`. Fastest driver by a wide margin. |
| `psycopg[binary]>=3.2` | Synchronous driver Alembic uses. Alembic does not work well with async drivers — migrations should run on a blocking connection. Running both drivers against one DB is normal (Alembic during migrate; asyncpg during app runtime). `[binary]` bundles prebuilt wheels so we avoid needing system `libpq-dev`. |
| `alembic>=1.14` | Migration tool. 1.14 has the `check` command used in CI migration-drift detection. |
| `apscheduler>=3.10` | In-process scheduler for recon + posting jobs. Chosen over Celery because Celery is overkill for a single-instance portfolio demo; APScheduler runs in the same process as FastAPI. |
| `jinja2>=3.1` | Template engine for the HTMX dashboard. 3.1 has the autoescape-on-by-default that FastAPI expects. |
| `stripe>=11.0` | Official Stripe SDK. Used only for webhook signature verification in the core (the Node edge does primary verification; core may re-verify during replay/audit). |
| `pydantic>=2.9` | Models, FastAPI request/response validation. v2 is a different API from v1 — we're on v2. |
| `pydantic-settings>=2.6` | The `BaseSettings` class was split out of Pydantic v2 core into this separate package. Reads env vars + `.env` files with type validation. Replaces hand-rolled `os.environ.get(...)` + manual casting. |
| `httpx>=0.27` | Async HTTP client. Used by Zuora client stubs and by tests that hit the FastAPI app in-process (`ASGITransport`). |

### Dev dependencies
```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "hypothesis>=6.118",
  "ruff>=0.7",
  "mypy>=1.13",
]
```

| Dep | Why |
|-----|-----|
| `pytest>=8.3` | Test runner. |
| `pytest-asyncio>=0.24` | Async test support. 0.24 made `asyncio_mode = "auto"` the recommended setting — no more `@pytest.mark.asyncio` on every test. |
| `hypothesis>=6.118` | Property-based testing. This is the signal library for Task 26–27. |
| `ruff>=0.7` | Linter + formatter. Replaces black/flake8/isort/pyupgrade. Single tool = fewer inconsistencies. |
| `mypy>=1.13` | Static type checker. We write type hints everywhere; mypy catches the bugs those type hints document. |

**Rejected dev deps:**
- `black` — ruff format replaces it.
- `isort` — ruff replaces it.
- `coverage` — we don't have a coverage target, and property tests already exercise invariants better than coverage would.
- `factory-boy` — our models are simple enough that fixture functions in `conftest.py` suffice.

### Build + pytest + ruff config
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/finledger"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]
```

| Config | Why |
|--------|-----|
| `hatchling` build backend | Modern PEP 517 build backend, bundled with Python's packaging ecosystem, zero config needed. Alternative: `setuptools` (more config, older patterns) or `poetry-core` (ties the project to Poetry tooling). |
| `packages = ["src/finledger"]` | Tells hatchling our importable code lives under `src/finledger/`. The src-layout prevents accidentally importing the in-tree package via `sys.path` weirdness during tests. |
| `ruff line-length = 100` | Not 80 (too short for type-annotated Python), not 120 (unreadable side-by-side). 100 is the project convention. |
| `asyncio_mode = "auto"` | Every async test is automatically awaited by pytest-asyncio. Without this, every async test needs `@pytest.mark.asyncio` decoration. |
| `pythonpath = ["src"]` | Lets pytest find the `finledger` package without `pip install -e`. Paired with the src-layout. |
| `testpaths = ["tests"]` | Pytest collects only from `tests/`, never accidentally from `src/` (which has no tests). |

---

## File 2: `core/alembic.ini`

Standard Alembic config. The only non-default line:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql://finledger:finledger@localhost:5432/finledger
```

### Why

| Line | Reason |
|------|--------|
| `script_location = alembic` | Tells Alembic where to find `env.py` and `versions/`. We put them at `core/alembic/` (not `core/src/finledger/alembic/`) because migrations aren't part of the importable package — they're tooling. |
| `sqlalchemy.url = ...` | Default URL for local dev. Gets overridden at runtime by `env.py` reading `DATABASE_URL` from env. Keeping a default means `alembic upgrade head` works out-of-the-box without exports. |

### Why the bottom logging config is verbose but mostly irrelevant

The `[loggers]`, `[handlers]`, `[formatters]` sections come straight from the Alembic template. We set `level = WARN` on root and sqlalchemy (no migration spam in normal output) and `level = INFO` on alembic itself (we do want to see "Running upgrade X -> Y"). Trimming this further is not worth the time — nothing else in the project uses this logging config.

---

## File 3: `core/alembic/env.py`

The critical piece:

```python
if os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
```

### Why

Alembic reads its URL from `alembic.ini` by default. In CI, in production, and for anyone whose local Postgres isn't at the default URL, hard-coded `alembic.ini` URLs are wrong. This block says: if `DATABASE_URL` env is set, it wins over the ini file. Result: `DATABASE_URL=... alembic upgrade head` works in every environment.

We check `os.getenv(...)` rather than just reading `os.environ["DATABASE_URL"]` because the latter raises KeyError when unset — the ini default is the fallback.

### `target_metadata = None` and why autogenerate is NOT configured

```python
target_metadata = None
```

Normally this would be `target_metadata = SomeBase.metadata` to enable `alembic revision --autogenerate`. We deliberately set it to `None` because:

1. **Autogenerate is a trap for this project.** We have DB-level things (triggers, CHECK constraints, schemas, indexes with partial WHERE clauses) that autogenerate doesn't reliably handle. Writing migrations by hand keeps them correct.
2. **Every migration in this plan has handcrafted SQL.** None benefit from autogenerate.

Setting `target_metadata = None` means running `alembic revision --autogenerate` produces an empty migration — loud feedback that we're not doing autogenerate.

### Why there's no `async_engine_from_config`

Alembic runs migrations synchronously. Mixing async drivers with Alembic's internal transaction management causes rare but hard-to-debug deadlocks. We use psycopg (sync) for migrations, asyncpg for app runtime. `env.py` uses `engine_from_config(...)` — the sync path — deliberately.

---

## File 4: `core/src/finledger/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://finledger:finledger@localhost:5432/finledger"
    stripe_webhook_secret: str = "whsec_test_placeholder"
    stripe_api_key: str = "sk_test_placeholder"
    zuora_webhook_secret: str = "zuora_test_placeholder"


settings = Settings()
```

### Why

| Element | Reason |
|---------|--------|
| `BaseSettings` subclass | Type-safe env var loading. Misspell `DATABASE_URL` in your env and you'll get `ValidationError` immediately, not a mysterious connection refusal later. |
| `env_file = ".env"` | Reads `.env` from the current working directory if present. In production we don't have a `.env`, env vars are set directly by the orchestrator — BaseSettings prefers real env vars over the file, so this works everywhere. |
| `extra = "ignore"` | `.env` files often accumulate unrelated vars (other services, local overrides). Without `ignore`, an unknown var in `.env` would error out. Tradeoff: typos in env var names are silently ignored. Acceptable because the defaults are populated — misspelling just means the default silently wins, which surfaces as a connection error in a way that points you back here. |
| Defaults inline | Lets `Settings()` succeed with no env at all. Good for tests and first-run demos. Real deployments override via env. |
| Module-level `settings = Settings()` | Singleton import. Every module that needs config does `from finledger.config import settings` — constructed once, shared everywhere. |

### Rejected alternatives

- **`os.environ.get("DATABASE_URL", default)` everywhere.** Rejected: no type checking, no validation, defaults scattered across the codebase.
- **A `.env` loader in `__init__.py` via `python-dotenv`.** Rejected: pydantic-settings already does it, no need for a second tool.
- **Pass config around as a dict/dataclass through function args.** Rejected: makes every async function signature longer for a value that's effectively global-read-only.

---

## File 5: `core/src/finledger/db.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from finledger.config import settings


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://")


engine = create_async_engine(_async_url(settings.database_url), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
```

### Why

| Element | Reason |
|---------|--------|
| `_async_url()` helper | The `DATABASE_URL` in `.env` is the standard libpq form (`postgresql://`). SQLAlchemy's async support needs the driver-qualified form (`postgresql+asyncpg://`). Converting in one place = don't-repeat-yourself and the env file stays tool-neutral. |
| `create_async_engine(..., pool_pre_ping=True)` | `pool_pre_ping` issues a cheap `SELECT 1` on a connection before handing it to the app. Without it, a dropped TCP connection (DB restart, idle timeout) shows up as a mysterious error on the next query. With it, stale connections are transparently replaced. Cost: one round-trip per checkout, negligible. |
| `async_sessionmaker(..., expire_on_commit=False)` | By default SQLAlchemy expires all loaded attributes after commit — every read post-commit re-queries. We almost never want that in async code (commits are frequent; re-queries are expensive). Setting `False` means commit is a no-op on the Python-side object graph. |
| `class_=AsyncSession` | Explicit. The sessionmaker accepts a session class; we want async ones. |
| Module-level `engine` + `SessionLocal` | Shared across the app. One engine per process = one connection pool. Creating engines per-request is a classic bug that exhausts DB connections. |

---

## What this task does NOT do

- **No models.** Those come in Task 5+ (after the first migration creates tables to model).
- **No FastAPI app.** Task 25.
- **No tests yet.** Task 3 writes the first test.
- **No first migration.** Task 2 creates schemas; this task just wires Alembic up so Task 2 can write a migration.

---

## Verification after task completes

1. `cd core && pip install -e '.[dev]'` succeeds (produces `finledger.egg-info/` — ignored by `.gitignore`).
2. `python -c "from finledger.config import settings; print(settings.database_url)"` prints the default URL.
3. `python -c "from finledger.db import engine; print(engine)"` prints an `AsyncEngine` repr.
4. `alembic history` succeeds and shows an empty history.
5. Six files committed: `pyproject.toml`, `alembic.ini`, `alembic/env.py`, `alembic/versions/.gitkeep`, `src/finledger/__init__.py`, `src/finledger/config.py`, `src/finledger/db.py`.

---

## Open questions

None. Every decision above has a stated alternative. Push back if you disagree with:

- `extra = "ignore"` over `extra = "forbid"` on Settings (I traded strictness for robustness-to-messy-env; arguable)
- Using both `asyncpg` and `psycopg` (two drivers for one DB feels weird but is industry-standard for Alembic + async stacks)
- Pinning minimums (`>=`) rather than exact versions (I'm relying on Python packaging to resolve a coherent set)
