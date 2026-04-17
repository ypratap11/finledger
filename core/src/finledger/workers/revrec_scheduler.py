"""Standalone scheduler process: runs revrec daily at 01:00 UTC.

Start with:  .venv/Scripts/python -m finledger.workers.revrec_scheduler

Tested manually by running the module, triggering the job via a REPL
call to run_for_yesterday(), and verifying a RecognitionRun row appears.
"""
import asyncio
import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from finledger.db import SessionLocal
from finledger.revrec.engine import run_recognition


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("revrec_scheduler")


async def run_for_yesterday() -> None:
    through = date.today() - timedelta(days=1)
    log.info("starting daily recognition run for %s", through)
    async with SessionLocal() as s:
        run = await run_recognition(s, through_date=through)
        await s.commit()
    log.info(
        "done: obligations_processed=%d total_cents=%d je=%s",
        run.obligations_processed, run.total_recognized_cents, run.journal_entry_id,
    )


async def main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_for_yesterday, CronTrigger(hour=1, minute=0))
    scheduler.start()
    log.info("revrec scheduler started (daily 01:00 UTC)")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
