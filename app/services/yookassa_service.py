import logging
import uuid
from typing import Any

from yookassa import Configuration, Payment as YooPayment
from yookassa.domain.response import PaymentResponse

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


def create_payment(tg_user_id: int, return_url: str | None = None) -> dict[str, Any]:
    idempotence_key = str(uuid.uuid4())

    payment_data = {
        "amount": {
            "value": settings.product_price,
            "currency": settings.product_currency,
        },
        "confirmation": {
            "type": "redirect",
            "return_url": return_url or settings.base_url or "https://t.me",
        },
        "capture": True,
        "description": "Методика снижения веса + закрытый чат",
        "metadata": {
            "tg_user_id": str(tg_user_id),
        },
    }

    payment: PaymentResponse = YooPayment.create(payment_data, idempotence_key)

    confirmation_url = None
    if payment.confirmation and hasattr(payment.confirmation, "confirmation_url"):
        confirmation_url = payment.confirmation.confirmation_url

    logger.info(
        "Created payment id=%s status=%s user=%s",
        payment.id,
        payment.status,
        tg_user_id,
    )

    return {
        "id": payment.id,
        "status": payment.status,
        "confirmation_url": confirmation_url,
        "amount": payment.amount.value if payment.amount else settings.product_price,
        "currency": payment.amount.currency if payment.amount else settings.product_currency,
    }


def get_payment(payment_id: str) -> PaymentResponse | None:
    try:
        payment = YooPayment.find_one(payment_id)
        return payment
    except Exception as e:
        logger.exception("Failed to fetch payment %s: %s", payment_id, type(e).__name__)
        return None


def is_valid_succeeded_payment(payment: PaymentResponse) -> bool:
    if payment is None:
        return False
    if payment.status != "succeeded":
        return False
    if not payment.amount:
        return False
    if str(payment.amount.value) != settings.product_price:
        return False
    if payment.amount.currency != settings.product_currency:
        return False
    return True
