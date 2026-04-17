import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from finledger.ui.app import app
from finledger.ui.routes.inbox import get_session as inbox_get_session
from finledger.ui.routes.journal import get_session as journal_get_session
from finledger.ui.routes.recon import get_session as recon_get_session
from finledger.ui.routes.flow import get_session as flow_get_session


@pytest.fixture
def client_with_fresh_db():
    """Per-test sync engine so the UI routes (sync psycopg) can be exercised
    via ASGITransport within an asyncio event loop without async<->sync clashes."""
    test_engine = create_engine(
        "postgresql+psycopg://finledger:finledger@localhost:5432/finledger"
    )
    TestSession = sessionmaker(test_engine, expire_on_commit=False)

    def override():
        with TestSession() as s:
            yield s

    app.dependency_overrides[inbox_get_session] = override
    app.dependency_overrides[journal_get_session] = override
    app.dependency_overrides[recon_get_session] = override
    app.dependency_overrides[flow_get_session] = override
    yield app
    app.dependency_overrides.clear()
    test_engine.dispose()


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
