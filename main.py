from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from telegram import BotCommand, Update
from telegram.ext import ContextTypes

from config import settings
from db import init_db
from handlers import student_onboard
from handlers import tutor
from handlers import apply
from handlers import recruiter
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
    await app.bot.set_my_commands([
        BotCommand("start", "Set up your profile"),
        BotCommand("menu", "Open the main menu"),
        BotCommand("recruiter", "Switch to recruiter mode"),
        BotCommand("find", "Search for candidates"),
        BotCommand("help", "Show all commands"),
    ])
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
    app.add_handler(CommandHandler("menu", _menu_cmd))
    app.add_handler(CommandHandler("help", _help_cmd))
    app.add_handler(CommandHandler("recruiter", recruiter.start))
    app.add_handler(CommandHandler("find", recruiter.find))

    app.add_handler(CallbackQueryHandler(student_onboard.handle_callback, pattern=r"^onb:"))
    app.add_handler(CallbackQueryHandler(tutor.handle_callback, pattern=r"^tutor:"))
    app.add_handler(CallbackQueryHandler(apply.handle_callback, pattern=r"^apply:"))
    app.add_handler(CallbackQueryHandler(recruiter.handle_rec_callback, pattern=r"^rec:msg:"))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_text_message)
    )

    return app


async def _menu_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=student_onboard.get_main_menu_inline(),
    )


async def _help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*PlaceMate Commands*\n\n"
        "/start — Set up your profile\n"
        "/menu — Open the main menu\n"
        "/recruiter — Switch to recruiter mode\n"
        "/find — Search for candidates (recruiter)\n"
        "/help — Show this message",
        parse_mode="Markdown",
        reply_markup=student_onboard.get_main_menu_inline(),
    )


async def _route_text_message(update, ctx):
    """Route text messages to the appropriate handler based on session state."""
    tg_id = update.effective_user.id
    if recruiter.RECRUITER_STATE.get(tg_id):
        await recruiter.handle_recruiter_email(update, ctx)
    else:
        await student_onboard.handle_text(update, ctx)


if __name__ == "__main__":
    import asyncio
    logger.info("Starting PlaceMate bot...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    build_app().run_polling()
