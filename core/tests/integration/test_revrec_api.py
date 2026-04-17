import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ui.app import app
from finledger.ui.routes.revrec import get_async_session as revrec_get_session


@pytest_asyncio.fixture
async def async_client():
    test_engine = create_async_engine(
        "postgresql+asyncpg://finledger:finledger@localhost:5432/finledger"
    )
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override():
        async with TestSession() as s:
            yield s

    app.dependency_overrides[revrec_get_session] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    ) as c:
        yield c
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_create_contract_returns_id(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "API-TEST-1",
        "customer_id": "C-42",
        "effective_date": "2026-05-01",
        "total_amount_cents": 12000,
        "currency": "USD",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["external_ref"] == "API-TEST-1"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_contract_is_idempotent_on_external_ref(async_client):
    body = {
        "external_ref": "API-TEST-2",
        "effective_date": "2026-05-01",
        "total_amount_cents": 12000,
    }
    r1 = await async_client.post("/revrec/contracts", json=body)
    r2 = await async_client.post("/revrec/contracts", json=body)
    assert r1.json()["id"] == r2.json()["id"]
