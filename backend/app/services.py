from __future__ import annotations
import html
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import func, select
from .config import get_settings
from .database import SessionLocal
from .models import AuditAction, AuditLog, Delivery, Job, JobStatus, User

settings = get_settings()


def app_button(text: str = "Открыть MiniApp") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.public_base_url))


def job_keyboard(job_id: int, can_claim: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if can_claim:
        buttons.append([InlineKeyboardButton(text="Взять заявку в работу", callback_data=f"claim:{job_id}")])
    # buttons.append([app_button("Посмотреть заявки")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# def full_job_keyboard() -> InlineKeyboardMarkup:
#     return InlineKeyboardMarkup(inline_keyboard=[[app_button("Посмотреть заявку")]])

def full_job_keyboard() -> None:
    return None


def display_name(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return user.first_name
    return str(user.telegram_id)


async def notify_admins(bot: Bot, text: str) -> None:
    async with SessionLocal() as session:
        admins = (await session.scalars(select(User).where(User.is_admin.is_(True), User.is_active.is_(True)))).all()
    for admin in admins:
        try:
            await bot.send_message(admin.telegram_id, text)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass


async def active_count(session, user_id: int) -> int:
    return int(await session.scalar(select(func.count(Job.id)).where(Job.assignee_id == user_id, Job.status == JobStatus.ACTIVE)) or 0)


async def eligible_cutoff(job: Job) -> Decimal:
    elapsed_minutes = max(0, int((datetime.now(timezone.utc) - job.offering_started_at).total_seconds() // 60))
    wave = min(4, elapsed_minutes // 10)
    return Decimal(str(5 - wave))


async def dispatch_waiting_jobs(bot: Bot, only_job_id: int | None = None) -> None:
    async with SessionLocal() as session:
        stmt = select(Job).where(Job.status == JobStatus.WAITING)
        if only_job_id is not None:
            stmt = stmt.where(Job.id == only_job_id)
        jobs = (await session.scalars(stmt.order_by(Job.created_at))).all()
        for job in jobs:
            cutoff = await eligible_cutoff(job)
            candidates = (await session.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    User.is_admin.is_(False),
                    User.rating >= cutoff,
                ).order_by(User.rating.desc(), User.id)
            )).all()
            for user in candidates:
                sent = await session.scalar(select(Delivery.id).where(
                    Delivery.job_id == job.id, Delivery.user_id == user.id, Delivery.round == job.notification_round
                ))
                if sent:
                    continue
                can_claim = (await active_count(session, user.id)) < 5
                text = f"<b>Новая заявка #{job.id}</b>\n\n{html.escape(job.public_text)}"
                if not can_claim:
                    text += "\n\nУ вас уже 5 активных заявок. Взять ещё одну пока нельзя."
                try:
                    message = await bot.send_message(
                        user.telegram_id, text, parse_mode="HTML", reply_markup=job_keyboard(job.id, can_claim)
                    )
                except (TelegramForbiddenError, TelegramBadRequest):
                    continue
                session.add(Delivery(job_id=job.id, user_id=user.id, round=job.notification_round,
                                     chat_id=user.telegram_id, message_id=message.message_id))
                await session.commit()


@dataclass
class ClaimResult:
    ok: bool
    reason: str | None = None
    job: Job | None = None
    user: User | None = None


async def claim_job(
    job_id: int,
    telegram_id: int,
    require_delivery: bool = False,
) -> ClaimResult:
    async with SessionLocal() as session:
        async with session.begin():
            job = await session.scalar(
                select(Job)
                .where(Job.id == job_id)
                .with_for_update()
            )

            if job is None or job.status != JobStatus.WAITING:
                return ClaimResult(False, "Эту заявку уже взял другой исполнитель.")

            user = await session.scalar(
                select(User)
                .where(User.telegram_id == telegram_id)
                .with_for_update()
            )

            if user is None or not user.is_active or user.is_admin:
                return ClaimResult(False, "У вас нет доступа к получению заявок.")

            if require_delivery:
                delivery_id = await session.scalar(
                    select(Delivery.id).where(
                        Delivery.job_id == job.id,
                        Delivery.user_id == user.id,
                        Delivery.round == job.notification_round,
                    )
                )

                if delivery_id is None:
                    return ClaimResult(False, "Эта заявка пока недоступна вам.")

            if await active_count(session, user.id) >= 5:
                return ClaimResult(False, "У вас уже 5 активных заявок.")

            job.status = JobStatus.ACTIVE
            job.assignee_id = user.id

            session.add(
                AuditLog(
                    job_id=job.id,
                    actor_id=user.id,
                    action=AuditAction.ASSIGNED,
                )
            )

        return ClaimResult(True, job=job, user=user)


async def update_messages_after_claim(bot: Bot, job: Job, assignee: User) -> None:
    async with SessionLocal() as session:
        deliveries = (await session.scalars(select(Delivery).where(
            Delivery.job_id == job.id, Delivery.round == job.notification_round
        ))).all()
    for delivery in deliveries:
        try:
            if delivery.user_id == assignee.id:
                await bot.edit_message_text(
                    chat_id=delivery.chat_id,
                    message_id=delivery.message_id,
                    text=f"<b>Заявка #{job.id} в работе</b>\n\n{html.escape(job.full_text)}",
                    parse_mode="HTML",
                    reply_markup=full_job_keyboard(),
                )
            else:
                await bot.delete_message(delivery.chat_id, delivery.message_id)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
    await notify_admins(bot, f"✅ Заявке #{job.id} назначен исполнитель: {display_name(assignee)}")


async def delete_round_messages(bot: Bot, job: Job) -> None:
    async with SessionLocal() as session:
        deliveries = (await session.scalars(select(Delivery).where(
            Delivery.job_id == job.id, Delivery.round == job.notification_round
        ))).all()
    for delivery in deliveries:
        try:
            await bot.delete_message(delivery.chat_id, delivery.message_id)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass

async def delete_messages_for_round(bot: Bot, job_id: int, round_number: int) -> None:
    async with SessionLocal() as session:
        deliveries = (await session.scalars(select(Delivery).where(
            Delivery.job_id == job_id, Delivery.round == round_number
        ))).all()
    for delivery in deliveries:
        try:
            await bot.delete_message(delivery.chat_id, delivery.message_id)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
