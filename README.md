# FinLedger

Quote-to-revenue pipeline portfolio project. See `docs/superpowers/specs/2026-04-14-finledger-design.md`.

## Run

    docker compose up -d postgres
    cd core && uv sync && alembic upgrade head
    uv run uvicorn finledger.ui.app:app --reload
    cd ../ingest-edge && npm install && npm run dev
