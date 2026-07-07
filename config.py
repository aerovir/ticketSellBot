from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ticketbot"

    # Telegram
    telegram_token: Optional[str] = None
    telegram_channel_id: Optional[str] = None  # @username или числовой ID канала для анонсов

    # VK
    vk_token: Optional[str] = None
    vk_group_id: Optional[str] = None

    # MAX
    max_token: Optional[str] = None

    # App
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
