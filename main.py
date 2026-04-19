from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config import settings
from db import init_db
from handlers import student_onboard
from handlers import tutor
from handlers import apply
from handlers import recruiter
from handlers import demo
from workers.watcher_poll import watcher_loop

load_dotenv()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("placemate")


async def post_init(app: Application) -> None:
    await init_db()
    logger.info("Database initialized")
    asyncio.create_task(watcher_loop(app.bot))
    logger.info("Watcher loop launched")


def build_app() -> Application:
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", student_onboard.start))
    app.add_handler(CommandHandler("demo", demo.run))
    app.add_handler(CommandHandler("help", demo.help_cmd))
    app.add_handler(CommandHandler("recruiter", recruiter.start))
    app.add_handler(CommandHandler("find", recruiter.find))

    app.add_handler(CallbackQueryHandler(student_onboard.handle_callback, pattern=r"^onb:"))
    app.add_handler(CallbackQueryHandler(tutor.handle_callback, pattern=r"^tutor:"))
    app.add_handler(CallbackQueryHandler(apply.handle_callback, pattern=r"^apply:"))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_text_message)
    )

    return app


async def _route_text_message(update, ctx):
    """Route text messages to the appropriate handler based on session state."""
    tg_id = update.effective_user.id
    if recruiter.RECRUITER_STATE.get(tg_id):
        await recruiter.handle_recruiter_email(update, ctx)
    else:
        await student_onboard.handle_text(update, ctx)


if __name__ == "__main__":
    logger.info("Starting PlaceMate bot...")
    build_app().run_polling()
