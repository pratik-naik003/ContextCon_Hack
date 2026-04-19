from __future__ import annotations

import asyncio
import json
import logging
import os

from telegram import Bot

from crustdata import Crustdata
from db import all_students_with_companies, insert_event, recent_event_signatures
from workers.event_dispatcher import dispatch_event

logger = logging.getLogger("placemate.watcher")


async def watcher_loop(bot: Bot) -> None:
    poll_interval = int(os.getenv("WATCHER_POLL_SECONDS", "60"))
    cd = Crustdata()
    logger.info("Watcher loop started, polling every %ds", poll_interval)

    while True:
        try:
            rows = await all_students_with_companies()
            seen = await recent_event_signatures()
            new_events = 0
            companies_checked = 0

            for student_id, (student, companies) in rows.items():
                for comp in companies:
                    companies_checked += 1
                    try:
                        jobs = await cd.job_listings(comp["company_id"])
                        results = jobs.get("results", jobs.get("job_listings", []))
                        for job in results[:5]:
                            job_id = job.get("id", job.get("job_id", ""))
                            sig = f"{comp['company_id']}:new_jd:{job_id}"
                            if sig in seen:
                                continue
                            event_id = await insert_event(
                                comp["company_id"],
                                comp["company_name"],
                                "new_jd",
                                json.dumps(job),
                            )
                            await dispatch_event(bot, student, comp, job, event_id)
                            new_events += 1
                    except Exception as e:
                        logger.warning("Job fetch failed for %s: %s", comp.get("company_name"), e)

            logger.info(
                "Watcher poll complete — %d new events, %d companies checked",
                new_events, companies_checked,
            )
        except Exception as e:
            logger.error("Watcher loop error: %s", e)

        await asyncio.sleep(poll_interval)
