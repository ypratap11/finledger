import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ui.app import app
from finledger.ui.routes.inbox import get_session as inbox_get_session
from finledger.ui.routes.journal import get_session as journal_get_session
from finledger.ui.routes.recon import get_session as recon_get_session
from finledger.ui.routes.flow import get_session as flow_get_session
from finledger.ui.routes.revrec import (
    get_async_session as revrec_async_session,
    get_sync_session as revrec_sync_session,
)

ASYNC_URL = "postgresql+asyncpg://finledger:finledger@localhost:5432/finledger"
SYNC_URL = "postgresql+psycopg://finledger:finledger@localhost:5432/finledger"


@pytest_asyncio.fixture
async def client_with_fresh_db():
    sync_engine = create_engine(SYNC_URL)
    SyncTestSession = sessionmaker(sync_engine, expire_on_commit=False)
    async_engine = create_async_engine(ASYNC_URL)
    AsyncTestSession = async_sessionmaker(async_engine, expire_on_commit=False)

    def sync_override():
        with SyncTestSession() as s:
            yield s

    async def async_override():
        async with AsyncTestSession() as s:
            yield s

    app.dependency_overrides[inbox_get_session] = sync_override
    app.dependency_overrides[journal_get_session] = sync_override
    app.dependency_overrides[recon_get_session] = sync_override
    app.dependency_overrides[flow_get_session] = sync_override
    app.dependency_overrides[revrec_async_session] = async_override
    app.dependency_overrides[revrec_sync_session] = sync_override
    yield app
    app.dependency_overrides.clear()
    sync_engine.dispose()
    await async_engine.dispose()


@pytest.mark.asyncio
async def test_inbox_page_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "Source Events" in r.text


@pytest.mark.asyncio
async def test_journal_page_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/journal")
    assert r.status_code == 200
    assert "Journal Entries" in r.text


@pytest.mark.asyncio
async def test_recon_page_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/recon")
    assert r.status_code == 200
    assert "Reconciliation" in r.text


@pytest.mark.asyncio
async def test_flow_page_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/flow")
    assert r.status_code == 200
    assert "Pipeline" in r.text


@pytest.mark.asyncio
async def test_revrec_index_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/revrec")
    assert r.status_code == 200
    assert "Backlog" in r.text


@pytest.mark.asyncio
async def test_revrec_contracts_empty_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/revrec/contracts")
    assert r.status_code == 200
    assert "Contracts" in r.text


@pytest.mark.asyncio
async def test_revrec_runs_empty_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/revrec/runs")
    assert r.status_code == 200
    assert "Recognition Log" in r.text


@pytest.mark.asyncio
async def test_revrec_usage_empty_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/revrec/usage")
    assert r.status_code == 200
    assert "Usage Events" in r.text
