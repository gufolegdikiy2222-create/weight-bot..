import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from app.config import get_settings
from app.db.models import Payment, Purchase, User

logger = logging.getLogger(__name__)
settings = get_settings()


async def has_active_purchase(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(
        select(Purchase).where(Purchase.user_id == user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_or_create_user(
    session: AsyncSession,
    tg_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    start_param: str | None = None,
) -> User:
    result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    user = result.scalar_one_or_none()
    if user:
        # Update basic info if changed
        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if start_param and not user.start_param:
            user.start_param = start_param
        return user

    user = User(
        tg_user_id=tg_user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        start_param=start_param,
    )
    session.add(user)
    await session.flush()
    return user


async def create_pending_payment(
    session: AsyncSession,
    user: User,
    yookassa_payment_id: str,
    amount: str,
    currency: str,
    confirmation_url: str | None,
) -> Payment:
    payment = Payment(
        yookassa_payment_id=yookassa_payment_id,
        user_id=user.id,
        amount=amount,
        currency=currency,
        status="pending",
        confirmation_url=confirmation_url,
        processed=False,
    )
    session.add(payment)
    await session.flush()
    return payment


async def process_successful_payment(
    session: AsyncSession,
    bot: Bot,
    yookassa_payment_id: str,
    tg_user_id: int,
) -> bool:
    """
    Idempotent processing of succeeded payment.
    Returns True if access was granted (or already granted).
    """
    # Idempotency check
    result = await session.execute(
        select(Payment).where(Payment.yookassa_payment_id == yookassa_payment_id)
    )
    payment_record = result.scalar_one_or_none()

    if payment_record and payment_record.processed:
        logger.info("Payment %s already processed, skip", yookassa_payment_id)
        return True

    # Find user
    user_result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        logger.error("User tg_id=%s not found for payment %s", tg_user_id, yookassa_payment_id)
        return False

    # Create invite link (member_limit=1, expire 24h)
    expire_date = datetime.now(timezone.utc) + timedelta(hours=24)
    try:
        invite = await bot.create_chat_invite_link(
            chat_id=settings.product_chat_id,
            name=f"user_{tg_user_id}",
            member_limit=1,
            expire_date=expire_date,
        )
        invite_link = invite.invite_link
    except TelegramError as e:
        logger.exception("Failed to create invite link: %s", type(e).__name__)
        invite_link = None

    # Save purchase
    purchase = Purchase(
        user_id=user.id,
        payment_id=yookassa_payment_id,
        amount=settings.product_price,
        currency=settings.product_currency,
        invite_link=invite_link,
        material_sent=False,
    )
    session.add(purchase)

    # Mark payment processed
    if payment_record:
        payment_record.status = "succeeded"
        payment_record.processed = True
    else:
        # Payment record might be missing if webhook arrived before we saved pending
        payment_record = Payment(
            yookassa_payment_id=yookassa_payment_id,
            user_id=user.id,
            amount=settings.product_price,
            currency=settings.product_currency,
            status="succeeded",
            processed=True,
        )
        session.add(payment_record)

    await session.flush()

    # Send material + invite to user
    await _send_access_to_user(bot, tg_user_id, invite_link)

    # Notify admin if configured
    if settings.admin_chat_id:
        try:
            await bot.send_message(
                chat_id=settings.admin_chat_id,
                text=f"Новая покупка\nuser_id={tg_user_id}\npayment={yookassa_payment_id}",
            )
        except TelegramError:
            logger.warning("Failed to notify admin")

    logger.info("Access granted for user %s payment %s", tg_user_id, yookassa_payment_id)
    return True


async def _send_access_to_user(bot: Bot, tg_user_id: int, invite_link: str | None) -> None:
    from pathlib import Path

    text_parts = [
        "Оплата прошла. Доступ открыт.",
        "",
        "Ниже — материал и ссылка в закрытый чат.",
    ]

    if invite_link:
        text_parts.append("")
        text_parts.append(f"Ссылка в закрытый чат (действует 24 часа, один вход):\n{invite_link}")
    else:
        text_parts.append("")
        text_parts.append("Ссылка в чат временно недоступна. Напиши /status или свяжись с поддержкой.")

    try:
        await bot.send_message(chat_id=tg_user_id, text="\n".join(text_parts))

        # 1. file_id (лучший вариант после первой загрузки)
        if settings.material_file_id:
            await bot.send_document(
                chat_id=tg_user_id,
                document=settings.material_file_id,
                caption="Методика снижения веса",
            )
        # 2. локальный PDF из materials/
        else:
            local_pdf = Path(__file__).resolve().parents[2] / "materials" / "metodika_snizheniya_vesa.pdf"
            if local_pdf.exists():
                with open(local_pdf, "rb") as f:
                    await bot.send_document(
                        chat_id=tg_user_id,
                        document=f,
                        filename="Metodika_snizheniya_vesa.pdf",
                        caption="Методика снижения веса",
                    )
            elif settings.material_url:
                await bot.send_message(
                    chat_id=tg_user_id,
                    text=f"Материал: {settings.material_url}",
                )
            else:
                await bot.send_message(
                    chat_id=tg_user_id,
                    text="Материал временно недоступен. Напиши в поддержку.",
                )
    except TelegramError as e:
        logger.exception("Failed to send access message to %s: %s", tg_user_id, type(e).__name__)
