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
                    company_id = comp.get("company_id", "")
                    company_name = comp.get("company_name", "")
                    try:
                        cid_int = int(company_id) if str(company_id).isdigit() else None
                        result = await cd.job_search(
                            company_id=cid_int,
                            company_name=company_name if not cid_int else "",
                            limit=5,
                        )
                        job_listings = result.get("job_listings", []) if isinstance(result, dict) else []
                        for job in job_listings[:5]:
                            jd = job.get("job_details", {})
                            job_url = jd.get("url", "")
                            if not job_url:
                                continue
                            sig = f"{company_name}:new_jd:{job_url}"
                            if sig in seen:
                                continue
                            event_id = await insert_event(
                                company_id or company_name,
                                company_name,
                                "new_jd",
                                json.dumps(job),
                            )
                            await dispatch_event(bot, student, comp, job, event_id)
                            new_events += 1
                    except Exception as e:
                        logger.warning("Job fetch failed for %s: %s", company_name, e)

            logger.info(
                "Watcher poll complete — %d new events, %d companies checked",
                new_events, companies_checked,
            )
        except Exception as e:
            logger.error("Watcher loop error: %s", e)

        await asyncio.sleep(poll_interval)
