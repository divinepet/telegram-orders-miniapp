from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from .auth import current_user, require_admin
from .bot import bot
from .database import get_session
from .models import AuditAction, AuditLog, Delivery, Job, JobStatus, User
from .schemas import (
    AddUserRequest,
    CommentRequest,
    CompleteRequest,
    JobCreate,
    JobResponse,
    MeResponse,
    UserResponse,
)
from .services import (
    claim_job,
    delete_messages_for_round,
    dispatch_waiting_jobs,
    display_name,
    notify_admins,
    update_messages_after_claim,
)

router = APIRouter(prefix="/api")


def map_job(
    job: Job,
    admin: bool = False,
    user: User | None = None,
) -> JobResponse:
    is_assignee = (
        user is not None
        and job.assignee_id == user.id
    )

    can_see_full_text = admin or (
        is_assignee
        and job.status in (
            JobStatus.AWAITING_CALL,
            JobStatus.ACTIVE,
            JobStatus.COMPLETED,
        )
    )

    can_see_comment = admin or (
        is_assignee
        and job.status in (
            JobStatus.AWAITING_CALL,
            JobStatus.ACTIVE,
            JobStatus.COMPLETED,
        )
    )

    return JobResponse(
        id=job.id,
        public_text=job.public_text,
        full_text=job.full_text if can_see_full_text else None,
        status=job.status,
        created_at=job.created_at,
        closed_at=job.closed_at,
        final_amount=job.final_amount,
        assignee_name=display_name(job.assignee) if admin and job.assignee else None,

        comment_text=job.comment_text if can_see_comment else None,
        comment_created_at=job.comment_created_at if can_see_comment else None,
        comment_updated_at=job.comment_updated_at if can_see_comment else None,
    )


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(current_user)) -> MeResponse:
    return MeResponse(
        telegram_id=user.telegram_id, first_name=user.first_name, username=user.username,
        is_admin=user.is_admin, rating=user.rating,
    )


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.is_admin:
        stmt = (
            select(Job)
            .options(selectinload(Job.assignee))
            .order_by(Job.created_at.desc())
        )
    else:
        stmt = (
            select(Job)
            .outerjoin(
                Delivery,
                and_(
                    Delivery.job_id == Job.id,
                    Delivery.user_id == user.id,
                    Delivery.round == Job.notification_round,
                ),
            )
            .options(selectinload(Job.assignee))
            .where(
                or_(
                    and_(
                        Job.assignee_id == user.id,
                        Job.status.in_([
                            JobStatus.AWAITING_CALL,
                            JobStatus.ACTIVE,
                            JobStatus.COMPLETED,
                        ]),
                    ),
                    and_(
                        Job.status == JobStatus.WAITING,
                        Delivery.id.is_not(None),
                    ),
                )
            )
            .order_by(Job.created_at.desc())
        )

    jobs = (await session.scalars(stmt)).all()

    return [
        map_job(job, admin=user.is_admin, user=user)
        for job in jobs
    ]


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(payload: JobCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    require_admin(user)
    job = Job(public_text=payload.public_text.strip(), full_text=payload.full_text.strip())
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await dispatch_waiting_jobs(bot, only_job_id=job.id)
    return map_job(job, True)


@router.post("/jobs/{job_id}/claim", response_model=JobResponse)
async def claim_job_from_miniapp(
    job_id: int,
    user: User = Depends(current_user),
):
    if user.is_admin:
        raise HTTPException(403, "Администратор не может брать заявки в работу")

    result = await claim_job(
        job_id=job_id,
        telegram_id=user.telegram_id,
        require_delivery=True,
    )

    if not result.ok:
        raise HTTPException(409, result.reason or "Не удалось взять заявку")

    await update_messages_after_claim(bot, result.job, result.user)

    return map_job(
        result.job,
        admin=False,
        user=result.user,
    )

@router.post("/jobs/{job_id}/called", response_model=JobResponse)
async def mark_job_called(
    job_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        job = await session.scalar(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
        )

        if (
            not job
            or job.status != JobStatus.AWAITING_CALL
            or job.assignee_id != user.id
        ):
            raise HTTPException(
                409,
                "Заявка не ожидает звонка или назначена другому исполнителю",
            )

        job.status = JobStatus.ACTIVE

    await session.refresh(job)

    await notify_admins(
        bot,
        f"📞 Исполнитель {display_name(user)} созвонился с клиентом по заявке #{job.id}.",
    )

    return map_job(
        job,
        admin=False,
        user=user,
    )

@router.put("/jobs/{job_id}/comment", response_model=JobResponse)
async def save_job_comment(
    job_id: int,
    payload: CommentRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    text = payload.text.strip()

    if not text:
        raise HTTPException(422, "Комментарий не может быть пустым")

    async with session.begin():
        job = await session.scalar(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
        )

        if not job:
            raise HTTPException(404, "Заявка не найдена")

        if job.assignee_id != user.id:
            raise HTTPException(
                403,
                "Комментарий может оставить только исполнитель заявки",
            )

        if job.status not in (
            JobStatus.AWAITING_CALL,
            JobStatus.ACTIVE,
        ):
            raise HTTPException(
                409,
                "Комментарий можно изменять только пока заявка ожидает звонка или находится в работе",
            )

        if job.comment_text is None:
            job.comment_created_at = func.now()

        job.comment_text = text
        job.comment_updated_at = func.now()

    await session.refresh(job)

    return map_job(
        job,
        admin=False,
        user=user,
    )

@router.post("/jobs/{job_id}/complete", response_model=JobResponse)
async def complete_job(job_id: int, payload: CompleteRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        locked_user = await session.scalar(select(User).where(User.id == user.id).with_for_update())
        if not job or job.status != JobStatus.ACTIVE or job.assignee_id != user.id:
            raise HTTPException(409, "Заявка не находится у вас в работе")
        job.status = JobStatus.COMPLETED
        job.final_amount = payload.amount
        job.closed_at = func.now()
        locked_user.rating = min(Decimal("5.00"), locked_user.rating + Decimal("0.25"))
        session.add(AuditLog(job_id=job.id, actor_id=user.id, action=AuditAction.COMPLETED, amount=payload.amount))
    await session.refresh(job)
    await delete_messages_for_round(bot, job.id, job.notification_round)
    await notify_admins(bot, f"💰 Заявка #{job.id} выполнена исполнителем {display_name(user)}. Сумма: {payload.amount} ₽")
    return map_job(
        job,
        admin=False,
        user=user,
    )


@router.post("/jobs/{job_id}/decline", response_model=dict)
async def decline_job(job_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        locked_user = await session.scalar(select(User).where(User.id == user.id).with_for_update())
        if (
            not job
            or job.status not in (
                JobStatus.AWAITING_CALL,
                JobStatus.ACTIVE,
            )
            or job.assignee_id != user.id
        ):
            raise HTTPException(409, "Заявка не находится у вас в работе")
        previous_round = job.notification_round
        job.status = JobStatus.WAITING
        job.assignee_id = None
        job.notification_round += 1
        job.offering_started_at = func.now()
        job.comment_text = None
        job.comment_created_at = None
        job.comment_updated_at = None
        locked_user.rating = max(Decimal("1.00"), locked_user.rating - Decimal("0.50"))
        session.add(AuditLog(job_id=job.id, actor_id=user.id, action=AuditAction.DECLINED))
    await delete_messages_for_round(bot, job_id, previous_round)
    await notify_admins(bot, f"↩️ Исполнитель {display_name(user)} отказался от заявки #{job_id}.")
    await dispatch_waiting_jobs(bot, only_job_id=job_id)
    return {"ok": True}


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    require_admin(user)

    active_jobs_count = func.count(Job.id).filter(
        Job.status.in_([
            JobStatus.AWAITING_CALL,
            JobStatus.ACTIVE,
        ])
    ).label("active_jobs")

    completed_jobs_count = func.count(Job.id).filter(
        Job.status == JobStatus.COMPLETED
    ).label("completed_jobs")

    rows = (
        await session.execute(
            select(
                User,
                active_jobs_count,
                completed_jobs_count,
            )
            .outerjoin(Job, Job.assignee_id == User.id)
            .group_by(User.id)
            .order_by(User.is_admin.desc(), User.created_at.desc())
        )
    ).all()

    return [
        UserResponse(
            telegram_id=u.telegram_id,
            first_name=u.first_name,
            username=u.username,
            is_admin=u.is_admin,
            is_active=u.is_active,
            rating=u.rating,
            active_jobs=active_jobs,
            completed_jobs=completed_jobs,
        )
        for u, active_jobs, completed_jobs in rows
    ]


@router.post("/users", response_model=UserResponse, status_code=201)
async def add_user(payload: AddUserRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    require_admin(user)
    target = await session.scalar(select(User).where(User.telegram_id == payload.telegram_id))
    if target:
        target.is_active = True
    else:
        target = User(telegram_id=payload.telegram_id, is_active=True, is_admin=False)
        session.add(target)
    await session.commit()
    await session.refresh(target)
    return UserResponse(telegram_id=target.telegram_id, first_name=target.first_name, username=target.username,
                        is_admin=target.is_admin, is_active=target.is_active, rating=target.rating, active_jobs=0, completed_jobs=0)


@router.post("/users/{telegram_id}/ban", response_model=dict)
async def ban_user(telegram_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    require_admin(user)
    released: list[tuple[int, int]] = []
    async with session.begin():
        target = await session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
        if not target:
            raise HTTPException(404, "Пользователь не найден")
        if target.is_admin:
            raise HTTPException(409, "Администратора нельзя заблокировать из MiniApp")
        target.is_active = False
        jobs = (
            await session.scalars(
                select(Job)
                .where(
                    Job.assignee_id == target.id,
                    Job.status.in_([
                        JobStatus.AWAITING_CALL,
                        JobStatus.ACTIVE,
                    ]),
                )
                .with_for_update()
            )
        ).all()
        for job in jobs:
            released.append((job.id, job.notification_round))
            job.assignee_id = None
            job.status = JobStatus.WAITING
            job.notification_round += 1
            job.offering_started_at = func.now()

            job.comment_text = None
            job.comment_created_at = None
            job.comment_updated_at = None
    for job_id, old_round in released:
        await delete_messages_for_round(bot, job_id, old_round)
        await dispatch_waiting_jobs(bot, only_job_id=job_id)
    return {"ok": True, "released_jobs": len(released)}
