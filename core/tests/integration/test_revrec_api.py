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


@pytest.mark.asyncio
async def test_create_obligation_on_contract(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "OBL-TEST-1", "effective_date": "2026-05-01",
        "total_amount_cents": 12000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "Subscription",
        "pattern": "ratable_daily",
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "total_amount_cents": 12000,
    })
    assert r2.status_code == 201
    assert "id" in r2.json()


@pytest.mark.asyncio
async def test_create_obligation_rejects_ratable_without_end_date(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "OBL-TEST-2", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "bad", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "total_amount_cents": 1000,
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_run_recognition_endpoint(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "RUN-TEST-1", "effective_date": "2026-05-01",
        "total_amount_cents": 31000,
    })
    cid = r.json()["id"]
    await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "Sub", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 31000,
    })
    r2 = await async_client.post("/revrec/run", json={"through_date": "2026-05-10"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["obligations_processed"] == 1
    assert body["total_recognized_cents"] == 10000
