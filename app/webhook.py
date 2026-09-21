import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from telegram import Bot

from app.config import get_settings
from app.db.database import async_session_factory
from app.services.access_service import process_successful_payment
from app.services.yookassa_service import get_payment, is_valid_succeeded_payment

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


@router.post("/yookassa/webhook")
async def yookassa_webhook(request: Request) -> dict[str, str]:
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    obj = payload.get("object") or {}

    if event != "payment.succeeded":
        return {"status": "ignored"}

    payment_id = obj.get("id")
    if not payment_id:
        logger.warning("Webhook without payment id")
        return {"status": "ignored"}

    metadata = obj.get("metadata") or {}
    tg_user_id_raw = metadata.get("tg_user_id")
    if not tg_user_id_raw:
        logger.warning("Webhook payment %s without tg_user_id in metadata", payment_id)
        return {"status": "ignored"}

    try:
        tg_user_id = int(tg_user_id_raw)
    except (TypeError, ValueError):
        logger.warning("Invalid tg_user_id in metadata: %s", tg_user_id_raw)
        return {"status": "ignored"}

    payment = get_payment(payment_id)
    if not is_valid_succeeded_payment(payment):
        logger.warning(
            "Payment %s failed validation (status/amount/currency)",
            payment_id,
        )
        return {"status": "rejected"}

    bot: Bot = request.app.state.bot

    async with async_session_factory() as session:
        ok = await process_successful_payment(
            session=session,
            bot=bot,
            yookassa_payment_id=payment_id,
            tg_user_id=tg_user_id,
        )
        await session.commit()

    if ok:
        return {"status": "ok"}
    return {"status": "error"}
