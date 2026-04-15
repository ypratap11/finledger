import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ui.app import app
from finledger.ui.routes.inbox import get_session as inbox_get_session
from finledger.ui.routes.journal import get_session as journal_get_session
from finledger.ui.routes.recon import get_session as recon_get_session


@pytest_asyncio.fixture
async def client_with_fresh_db():
    """Override the module-level SessionLocal with a per-test engine so each
    test gets a session bound to the current event loop."""
    test_engine = create_async_engine(
        "postgresql+asyncpg://finledger:finledger@localhost:5432/finledger"
    )
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override():
        async with TestSession() as s:
            yield s

    app.dependency_overrides[inbox_get_session] = override
    app.dependency_overrides[journal_get_session] = override
    app.dependency_overrides[recon_get_session] = override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_inbox_page_returns_200(client_with_fresh_db):
    r = await client_with_fresh_db.get("/")
    assert r.status_code == 200
    assert "Source Events" in r.text


@pytest.mark.asyncio
async def test_journal_page_returns_200(client_with_fresh_db):
    r = await client_with_fresh_db.get("/journal")
    assert r.status_code == 200
    assert "Journal Entries" in r.text


@pytest.mark.asyncio
async def test_recon_page_returns_200(client_with_fresh_db):
    r = await client_with_fresh_db.get("/recon")
    assert r.status_code == 200
    assert "Reconciliation Runs" in r.text
