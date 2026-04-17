"""Seed revrec demo data: 3 contracts + obligations + a recognition run.

Run after seed_demo.py (which creates the chart of accounts and M1 ledger data).
Shows what the /revrec pages look like with realistic numbers.
"""
import asyncio
import uuid
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.models.revrec import Contract, PerformanceObligation
from finledger.revrec.engine import run_recognition

import os


def _async_url() -> str:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://finledger:finledger@localhost:5432/finledger",
    )
    return url.replace("postgresql+psycopg://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


ASYNC_URL = _async_url()


async def main() -> None:
    engine = create_async_engine(ASYNC_URL)
    S = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    contracts = [
        # Annual subscription, started 3 months ago (so ~25% recognized)
        {
            "ref": "I-ACME-2026-Q1",
            "customer": "ACME Corp",
            "start": date.today() - timedelta(days=90),
            "end": date.today() + timedelta(days=275),
            "amount": 120000_00,  # $120k
            "desc": "Annual platform subscription",
        },
        # Quarterly sub, started 30 days ago
        {
            "ref": "I-GLOBEX-Q2",
            "customer": "Globex",
            "start": date.today() - timedelta(days=30),
            "end": date.today() + timedelta(days=60),
            "amount": 30000_00,
            "desc": "Quarterly subscription",
        },
        # Annual sub starting next month (no recognition yet)
        {
            "ref": "I-INITECH-FUTURE",
            "customer": "Initech",
            "start": date.today() + timedelta(days=30),
            "end": date.today() + timedelta(days=395),
            "amount": 60000_00,
            "desc": "Annual subscription (future)",
        },
    ]

    async with S() as s:
        existing = {
            ref for (ref,) in (
                await s.execute(select(Contract.external_ref).where(
                    Contract.external_ref.in_([c["ref"] for c in contracts])
                ))
            ).all()
        }
        if existing:
            print(f"revrec demo already seeded ({len(existing)}/{len(contracts)} contracts exist) — skipping")
            await engine.dispose()
            return
        for c in contracts:
            contract = Contract(
                id=uuid.uuid4(),
                external_ref=c["ref"],
                customer_id=c["customer"],
                effective_date=c["start"],
                status="active",
                total_amount_cents=c["amount"],
                currency="USD",
                created_at=now,
            )
            s.add(contract)
            await s.flush()
            s.add(PerformanceObligation(
                id=uuid.uuid4(),
                contract_id=contract.id,
                description=c["desc"],
                pattern="ratable_daily",
                start_date=c["start"],
                end_date=c["end"],
                total_amount_cents=c["amount"],
                currency="USD",
                deferred_revenue_account_code="2000-DEFERRED-REV",
                revenue_account_code="4000-REV-SUB",
                created_at=now,
            ))
        await s.commit()

    # Run recognition through today
    async with S() as s:
        run = await run_recognition(s, through_date=date.today())
        await s.commit()
        print(f"Seeded 3 contracts. Recognition run: "
              f"obligations_processed={run.obligations_processed}, "
              f"total_recognized=${run.total_recognized_cents / 100:,.2f}")

    await engine.dispose()
    print("Done — open http://localhost:8003/revrec")


if __name__ == "__main__":
    asyncio.run(main())
