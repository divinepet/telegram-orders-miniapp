from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, MenuButtonWebApp, WebAppInfo
from fastapi import HTTPException
from .auth import TelegramIdentity, find_allowed_user
from .config import get_settings
from .database import SessionLocal
from .services import app_button, claim_job, update_messages_after_claim

settings = get_settings()
router = Router()
dp = Dispatcher()
dp.include_router(router)
bot = Bot(settings.bot_token)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    identity = TelegramIdentity(message.from_user.id, message.from_user.first_name, message.from_user.username)
    try:
        async with SessionLocal() as session:
            user = await find_allowed_user(session, identity)
            await session.commit()
    except HTTPException:
        await message.answer("Для вас бот недоступен.")
        return
    role = "администратор" if user.is_admin else "пользователь"
    await message.answer(
        f"Доступ разрешён. Ваша роль: {role}. Откройте приложение кнопкой ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[app_button()]]),
    )


@router.callback_query(F.data.startswith("claim:"))
async def claim_callback(callback: CallbackQuery) -> None:
    job_id = int(callback.data.split(":", 1)[1])
    result = await claim_job(job_id, callback.from_user.id)
    if not result.ok:
        await callback.answer(result.reason or "Не удалось взять заявку", show_alert=True)
        return
    await callback.answer("Заявка назначена вам")
    await update_messages_after_claim(bot, result.job, result.user)


async def configure_bot() -> None:
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Заявки", web_app=WebAppInfo(url=settings.public_base_url)))
