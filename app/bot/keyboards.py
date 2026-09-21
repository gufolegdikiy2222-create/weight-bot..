from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="Получить доступ — 990 ₽",
                    callback_data="buy",
                )
            ]
        ]
    )


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="Что входит?",
                    callback_data="info",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Получить доступ — 990 ₽",
                    callback_data="buy",
                )
            ],
        ]
    )
