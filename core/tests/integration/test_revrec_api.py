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


@pytest.mark.asyncio
async def test_list_contracts_empty(async_client):
    r = await async_client.get("/revrec/contracts", headers={"accept": "application/json"})
    assert r.status_code == 200
    assert r.json() == {"contracts": []}


@pytest.mark.asyncio
async def test_list_runs_empty(async_client):
    r = await async_client.get("/revrec/runs", headers={"accept": "application/json"})
    assert r.status_code == 200
    assert r.json() == {"runs": []}


@pytest.mark.asyncio
async def test_waterfall_json_has_months_and_total(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "WF-TEST-1", "effective_date": "2026-05-01",
        "total_amount_cents": 31000,
    })
    cid = r.json()["id"]
    await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "Sub", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 31000,
    })
    r2 = await async_client.get("/revrec/waterfall?months=12", headers={"accept": "application/json"})
    assert r2.status_code == 200
    body = r2.json()
    assert "months" in body and "total" in body
    assert body["total"] == 31000


# ---- M2a-1.5a: consumption API ----------------------------------------------

@pytest.mark.asyncio
async def test_create_consumption_obligation(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "CONSUMPTION-1", "effective_date": "2026-05-01",
        "total_amount_cents": 120000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "API calls",
        "pattern": "consumption",
        "start_date": "2026-05-01",
        "total_amount_cents": 120000,
        "units_total": 1000000,
        "unit_label": "API calls",
        "external_ref": "zuora-rpc-xyz",
    })
    assert r2.status_code == 201
    assert "id" in r2.json()


@pytest.mark.asyncio
async def test_create_consumption_obligation_without_units_total_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "CONSUMPTION-2", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "bad", "pattern": "consumption",
        "start_date": "2026-05-01", "total_amount_cents": 1000,
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_reject_units_total_on_ratable_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "CONSUMPTION-3", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "bad", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 1000,
        "units_total": 500,
    })
    assert r2.status_code == 422


async def _seed_consumption_via_api(async_client, *, ref_prefix, units_total=1000, total_cents=1000):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": ref_prefix, "effective_date": "2026-05-01",
        "total_amount_cents": total_cents,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "consumption",
        "pattern": "consumption",
        "start_date": "2026-05-01",
        "total_amount_cents": total_cents,
        "units_total": units_total,
    })
    return cid, r2.json()["id"]


@pytest.mark.asyncio
async def test_post_usage_event_success(async_client):
    _, oid = await _seed_consumption_via_api(
        async_client, ref_prefix="USAGE-API-1",
        units_total=1000000, total_cents=120000,
    )
    r3 = await async_client.post("/revrec/usage", json={
        "obligation_id": oid,
        "units": 1500,
        "occurred_at": "2026-03-15T10:30:00Z",
        "idempotency_key": "app-evt-abc",
    })
    assert r3.status_code == 201, r3.text
    body = r3.json()
    assert "id" in body
    assert "received_at" in body


@pytest.mark.asyncio
async def test_post_usage_duplicate_idempotency_key_409(async_client):
    _, oid = await _seed_consumption_via_api(
        async_client, ref_prefix="USAGE-API-2", units_total=100, total_cents=1000,
    )
    body = {
        "obligation_id": oid, "units": 1,
        "occurred_at": "2026-03-15T10:30:00Z",
        "idempotency_key": "dup-key-1",
    }
    r_a = await async_client.post("/revrec/usage", json=body)
    r_b = await async_client.post("/revrec/usage", json=body)
    assert r_a.status_code == 201
    assert r_b.status_code == 409


@pytest.mark.asyncio
async def test_post_usage_obligation_not_found_404(async_client):
    r = await async_client.post("/revrec/usage", json={
        "obligation_id": "00000000-0000-0000-0000-000000000000",
        "units": 1,
        "occurred_at": "2026-03-15T10:30:00Z",
        "idempotency_key": "nf-key",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_usage_pattern_mismatch_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "USAGE-API-MM", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "x", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 1000,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post("/revrec/usage", json={
        "obligation_id": oid,
        "units": 1,
        "occurred_at": "2026-03-15T10:30:00Z",
        "idempotency_key": "mm-key",
    })
    assert r3.status_code == 422


@pytest.mark.asyncio
async def test_post_usage_units_zero_422(async_client):
    _, oid = await _seed_consumption_via_api(
        async_client, ref_prefix="USAGE-API-ZERO", units_total=100,
    )
    r3 = await async_client.post("/revrec/usage", json={
        "obligation_id": oid,
        "units": 0,
        "occurred_at": "2026-03-15T10:30:00Z",
        "idempotency_key": "zero-key",
    })
    assert r3.status_code == 422


@pytest.mark.asyncio
async def test_list_usage_empty_json(async_client):
    r = await async_client.get("/revrec/usage", headers={"accept": "application/json"})
    assert r.status_code == 200
    assert r.json() == {"events": []}


@pytest.mark.asyncio
async def test_list_usage_returns_events_newest_first(async_client):
    _, oid = await _seed_consumption_via_api(
        async_client, ref_prefix="USAGE-LIST", units_total=1000,
    )
    for i in range(3):
        await async_client.post("/revrec/usage", json={
            "obligation_id": oid, "units": 10 * (i + 1),
            "occurred_at": f"2026-03-{10 + i}T10:00:00Z",
            "idempotency_key": f"list-key-{i}",
        })
    r3 = await async_client.get("/revrec/usage", headers={"accept": "application/json"})
    body = r3.json()
    assert len(body["events"]) == 3
    units = [e["units"] for e in body["events"]]
    assert units == [30, 20, 10]


# ---- M2a-1.5b: PAYG admin API ------------------------------------------------

@pytest.mark.asyncio
async def test_create_payg_obligation_happy(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-API-1", "effective_date": "2026-04-01",
        "total_amount_cents": 1,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "PAYG API",
        "pattern": "consumption_payg",
        "start_date": "2026-04-01",
        "price_per_unit_cents": 5,
        "unit_label": "API calls",
    })
    assert r2.status_code == 201, r2.text


@pytest.mark.asyncio
async def test_create_payg_without_price_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-API-2", "effective_date": "2026-04-01",
        "total_amount_cents": 1,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "no price", "pattern": "consumption_payg",
        "start_date": "2026-04-01",
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_reject_price_on_non_payg_pattern_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-API-3", "effective_date": "2026-04-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "ratable with price", "pattern": "ratable_daily",
        "start_date": "2026-04-01", "end_date": "2026-04-30",
        "total_amount_cents": 1000, "price_per_unit_cents": 5,
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_post_usage_to_payg_obligation_succeeds(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-USE", "effective_date": "2026-04-01",
        "total_amount_cents": 1,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "PAYG", "pattern": "consumption_payg",
        "start_date": "2026-04-01", "price_per_unit_cents": 10,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post("/revrec/usage", json={
        "obligation_id": oid, "units": 100,
        "occurred_at": "2026-04-15T10:00:00Z",
        "idempotency_key": "payg-usage-1",
    })
    assert r3.status_code == 201, r3.text


@pytest.mark.asyncio
async def test_admin_bill_payg_obligation_happy(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-BILL-1", "effective_date": "2026-04-01",
        "total_amount_cents": 1,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "PAYG bill", "pattern": "consumption_payg",
        "start_date": "2026-04-01", "price_per_unit_cents": 10,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post(f"/revrec/obligations/{oid}/bill", json={
        "invoice_amount_cents": 5000,
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "external_ref": "INV-PAYG-X",
    })
    assert r3.status_code == 201, r3.text
    assert "id" in r3.json()
    assert "journal_entry_id" in r3.json()


@pytest.mark.asyncio
async def test_admin_bill_idempotent_on_external_ref(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-BILL-IDEMP", "effective_date": "2026-04-01",
        "total_amount_cents": 1,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "PAYG", "pattern": "consumption_payg",
        "start_date": "2026-04-01", "price_per_unit_cents": 10,
    })
    oid = r2.json()["id"]
    body = {
        "invoice_amount_cents": 5000,
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "external_ref": "INV-DUP",
    }
    a = await async_client.post(f"/revrec/obligations/{oid}/bill", json=body)
    b = await async_client.post(f"/revrec/obligations/{oid}/bill", json=body)
    assert a.status_code == 201
    assert b.json()["id"] == a.json()["id"]


@pytest.mark.asyncio
async def test_admin_bill_non_payg_obligation_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "BILL-RATABLE", "effective_date": "2026-04-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "ratable", "pattern": "ratable_daily",
        "start_date": "2026-04-01", "end_date": "2026-04-30",
        "total_amount_cents": 1000,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post(f"/revrec/obligations/{oid}/bill", json={
        "invoice_amount_cents": 1000,
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
    })
    assert r3.status_code == 422
