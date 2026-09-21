import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers import (
    buy_handler,
    help_handler,
    info_callback,
    message_handler,
    start_handler,
    status_handler,
)
from app.config import get_settings
from app.db.database import init_db
from app.webhook import router as webhook_router

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
settings = get_settings()


def build_telegram_app() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("buy", buy_handler))
    app.add_handler(CallbackQueryHandler(buy_handler, pattern="^buy$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(MessageHandler(filters.TEXT & (\~filters.COMMAND), message_handler))
    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    tg_app = build_telegram_app()
    await tg_app.initialize()
    await tg_app.start()

    app.state.bot = tg_app.bot
    app.state.tg_app = tg_app

    base = (settings.base_url or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base:
        logger.error("BASE_URL is empty")
        raise RuntimeError("BASE_URL is required")
    webhook_url = f"{base}/telegram/webhook"
    await tg_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    logger.info("Telegram webhook set to %s", webhook_url)

    yield

    await tg_app.bot.delete_webhook()
    await tg_app.stop()
    await tg_app.shutdown()


app = FastAPI(title="Weight Bot", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(update: dict) -> dict[str, str]:
    tg_app: Application = app.state.tg_app
    await tg_app.process_update(Update.de_json(update, tg_app.bot))
    return {"status": "ok"}
