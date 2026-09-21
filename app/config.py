from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    yookassa_shop_id: str
    yookassa_secret_key: str
    product_chat_id: int
    base_url: str = ""
    admin_chat_id: int | None = None
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    product_price: str = "990.00"
    product_currency: str = "RUB"
    material_file_id: str | None = None
    material_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
