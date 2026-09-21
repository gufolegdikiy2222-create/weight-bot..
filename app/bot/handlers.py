import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import payment_keyboard, start_keyboard
from app.config import get_settings
from app.db.database import async_session_factory
from app.services.access_service import (
    create_pending_payment,
    get_or_create_user,
    has_active_purchase,
)
from app.services.reply_service import generate_reply
from app.services.yookassa_service import create_payment

logger = logging.getLogger(__name__)
settings = get_settings()


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    tg_user = update.effective_user
    start_param = None
    if context.args:
        start_param = context.args[0]

    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            tg_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            start_param=start_param,
        )
        already_bought = await has_active_purchase(session, user.id)
        await session.commit()

    if already_bought:
        await update.message.reply_text(
            "У тебя уже есть доступ. Материал и ссылка в чат были отправлены после оплаты.\n"
            "Если что-то не пришло — напиши /status."
        )
        return

    text = (
        "Привет. Здесь можно получить методику снижения веса и доступ в закрытый чат.\n\n"
        "Коротко: практический подход без жёстких запретов + поддержка в чате.\n"
        "Стоимость 990 ₽, один раз, доступ навсегда."
    )
    await update.message.reply_text(text, reply_markup=start_keyboard())


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "Продукт: методика снижения веса + закрытый чат.\n"
        "Цена: 990 ₽, один платёж, доступ навсегда.\n\n"
        "После оплаты сразу приходит материал и одноразовая ссылка в чат (действует 24 часа).\n\n"
        "Команды:\n"
        "/start — начать\n"
        "/buy — получить кнопку оплаты\n"
        "/status — проверить, куплен ли доступ\n"
        "/help — это сообщение"
    )
    await update.message.reply_text(text)


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    async with async_session_factory() as session:
        user = await get_or_create_user(session, tg_user_id=update.effective_user.id)
        bought = await has_active_purchase(session, user.id)
        await session.commit()

    if bought:
        await update.message.reply_text("Доступ куплен. Материал и ссылка в чат были отправлены после оплаты.")
    else:
        await update.message.reply_text(
            "Доступ ещё не куплен.",
            reply_markup=payment_keyboard(),
        )


async def buy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user = query.from_user
        message = query.message
    elif update.message:
        user = update.effective_user
        message = update.message
    else:
        return

    if not user or not message:
        return

    async with async_session_factory() as session:
        db_user = await get_or_create_user(
            session,
            tg_user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        if await has_active_purchase(session, db_user.id):
            await session.commit()
            text = "У тебя уже есть доступ. Повторно оплачивать не нужно."
            if update.callback_query:
                await query.edit_message_text(text)
            else:
                await message.reply_text(text)
            return

        try:
            payment_data = create_payment(tg_user_id=user.id)
        except Exception as e:
            logger.exception("Payment creation failed: %s", type(e).__name__)
            err_text = "Не получилось создать платёж. Попробуй чуть позже."
            if update.callback_query:
                await query.edit_message_text(err_text)
            else:
                await message.reply_text(err_text)
            return

        await create_pending_payment(
            session,
            user=db_user,
            yookassa_payment_id=payment_data["id"],
            amount=payment_data["amount"],
            currency=payment_data["currency"],
            confirmation_url=payment_data["confirmation_url"],
        )
        await session.commit()

    url = payment_data.get("confirmation_url")
    if not url:
        text = "Платёж создан, но ссылка на оплату не пришла. Попробуй /buy ещё раз."
        if update.callback_query:
            await query.edit_message_text(text)
        else:
            await message.reply_text(text)
        return

    text = (
        "Оплата 990 ₽.\n"
        "После успешной оплаты материал и ссылка в чат придут сюда автоматически.\n\n"
        f"Перейти к оплате:\n{url}"
    )
    if update.callback_query:
        await query.edit_message_text(text)
    else:
        await message.reply_text(text)


async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    text = (
        "Входит:\n"
        "• PDF с методикой\n"
        "• доступ в закрытый чат поддержки\n\n"
        "990 ₽ один раз, доступ навсегда.\n"
        "Никаких гарантий конкретного результата — это инструмент, а не волшебная таблетка."
    )
    await query.edit_message_text(text, reply_markup=payment_keyboard())


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not update.message.text:
        return

    tg_user = update.effective_user
    text = update.message.text.strip()

    async with async_session_factory() as session:
        await get_or_create_user(
            session,
            tg_user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        await session.commit()

    reply, show_buy = generate_reply(text)
    if show_buy:
        await update.message.reply_text(reply, reply_markup=payment_keyboard())
    else:
        await update.message.reply_text(reply)
