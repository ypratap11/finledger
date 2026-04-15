import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import text

TEST_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://finledger:finledger@localhost:5432/finledger")


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine(TEST_URL)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def session(engine):
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE inbox.source_events CASCADE"))
    yield
