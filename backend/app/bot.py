import asyncio

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MenuButtonWebApp,
    WebAppInfo,
)
from fastapi import HTTPException
from sqlalchemy import select

from .auth import TelegramIdentity, find_allowed_user
from .config import get_settings
from .database import SessionLocal
from .models import User
from .services import (
    app_button,
    claim_job,
    job_keyboard,
    update_messages_after_claim,
)

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


@router.message(Command("all"))
async def broadcast_handler(message: Message) -> None:
    identity = TelegramIdentity(message.from_user.id, message.from_user.first_name, message.from_user.username)
    try:
        async with SessionLocal() as session:
            sender = await find_allowed_user(session, identity)
            await session.commit()
    except HTTPException:
        await message.answer("Для вас бот недоступен.")
        return

    if not sender.is_admin:
        await message.answer("Команда доступна только администраторам.")
        return

    parts = (message.text or "").split(maxsplit=1)
    broadcast_text = parts[1].strip() if len(parts) > 1 else ""
    if not broadcast_text:
        await message.answer("Использование: /all <текст сообщения>")
        return

    async with SessionLocal() as session:
        recipients = (
            await session.scalars(
                select(User).where(User.is_active.is_(True))
            )
        ).all()

    sent = 0
    failed = 0

    for recipient in recipients:
        try:
            await bot.send_message(recipient.telegram_id, broadcast_text)
            sent += 1
        except TelegramRetryAfter as error:
            await asyncio.sleep(error.retry_after)
            try:
                await bot.send_message(recipient.telegram_id, broadcast_text)
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1

    await message.answer(
        f"Рассылка завершена. Доставлено: {sent}. Не доставлено: {failed}."
    )


@router.callback_query(F.data.startswith("claim:"))
async def claim_callback(callback: CallbackQuery) -> None:
    job_id = int(callback.data.split(":", 1)[1])

    await callback.answer()

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Да, взять заявку",
                            callback_data=f"confirm_claim:{job_id}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="Отмена",
                            callback_data=f"cancel_claim:{job_id}",
                        ),
                    ],
                ]
            )
        )


@router.callback_query(F.data.startswith("confirm_claim:"))
async def confirm_claim_callback(callback: CallbackQuery) -> None:
    job_id = int(callback.data.split(":", 1)[1])

    result = await claim_job(
        job_id,
        callback.from_user.id,
        require_delivery=True,
    )

    if not result.ok:
        await callback.answer(
            result.reason or "Не удалось взять заявку",
            show_alert=True,
        )
        return

    await callback.answer("Заявка назначена вам")

    await update_messages_after_claim(
        bot,
        result.job,
        result.user,
    )


@router.callback_query(F.data.startswith("cancel_claim:"))
async def cancel_claim_callback(callback: CallbackQuery) -> None:
    job_id = int(callback.data.split(":", 1)[1])

    await callback.answer("Отменено")

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=job_keyboard(
                job_id,
                can_claim=True,
            )
        )


async def configure_bot() -> None:
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Заявки", web_app=WebAppInfo(url=settings.public_base_url)))
