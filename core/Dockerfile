FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Build context is the repo root so we can pull in ../fixtures alongside core/
COPY core/pyproject.toml ./
COPY core/src ./src
COPY core/alembic.ini ./
COPY core/alembic ./alembic
COPY core/tests ./tests
COPY core/seed_demo.py core/seed_revrec_demo.py ./
COPY fixtures /fixtures

RUN pip install --no-cache-dir -e '.[dev]'

EXPOSE 8000

ENV DATABASE_URL=postgresql+psycopg://finledger:finledger@postgres:5432/finledger
ENV TEST_DATABASE_URL=postgresql+asyncpg://finledger:finledger@postgres:5432/finledger
