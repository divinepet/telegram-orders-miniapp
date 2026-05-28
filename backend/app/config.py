from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_telegram_ids: str = ""
    public_base_url: str
    database_url: str
    dev_auth_telegram_id: int | None = None

    model_config = SettingsConfigDict(
    env_file=".env",
    case_sensitive=False,
    extra="ignore",
    env_ignore_empty=True,
)

    @property
    def admins(self) -> set[int]:
        return {int(value.strip()) for value in self.admin_telegram_ids.split(",") if value.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
