FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
COPY seed_demo.py seed_revrec_demo.py ./

RUN pip install --no-cache-dir -e '.[dev]'

EXPOSE 8000

ENV DATABASE_URL=postgresql+psycopg://finledger:finledger@postgres:5432/finledger
ENV TEST_DATABASE_URL=postgresql+asyncpg://finledger:finledger@postgres:5432/finledger
