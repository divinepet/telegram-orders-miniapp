import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl
from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import get_settings
from .database import SessionLocal
from .models import User

settings = get_settings()


@dataclass
class TelegramIdentity:
    telegram_id: int
    first_name: str | None = None
    username: str | None = None


def validate_init_data(raw: str, max_age_seconds: int = 86400) -> TelegramIdentity:
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Telegram initData hash отсутствует")
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(401, "Некорректная подпись Telegram")
    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date < int(time.time()) - max_age_seconds:
        raise HTTPException(401, "Сессия MiniApp устарела, откройте приложение заново")
    user_data = json.loads(pairs.get("user", "{}"))
    if "id" not in user_data:
        raise HTTPException(401, "Telegram пользователь не найден")
    return TelegramIdentity(
        telegram_id=int(user_data["id"]),
        first_name=user_data.get("first_name"),
        username=user_data.get("username"),
    )


async def current_user(x_telegram_init_data: str | None = Header(default=None)) -> User:
    if settings.dev_auth_telegram_id and not x_telegram_init_data:
        identity = TelegramIdentity(settings.dev_auth_telegram_id, "Dev", "dev")
    elif x_telegram_init_data:
        identity = validate_init_data(x_telegram_init_data)
    else:
        raise HTTPException(401, "Откройте приложение внутри Telegram")
    async with SessionLocal() as session:
        user = await find_allowed_user(session, identity)
        await session.commit()
        return user


async def find_allowed_user(session: AsyncSession, identity: TelegramIdentity) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == identity.telegram_id))
    if user is None and identity.telegram_id in settings.admins:
        user = User(telegram_id=identity.telegram_id, is_admin=True, is_active=True)
        session.add(user)
        await session.flush()
    if user is None or not user.is_active:
        raise HTTPException(403, "Для вас бот недоступен")
    if identity.telegram_id in settings.admins and not user.is_admin:
        user.is_admin = True
    if identity.first_name:
        user.first_name = identity.first_name
    if identity.username:
        user.username = identity.username
    return user


def require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(403, "Доступно только администраторам")
