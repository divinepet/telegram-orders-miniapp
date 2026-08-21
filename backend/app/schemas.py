from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from .models import JobStatus


class MeResponse(BaseModel):
    telegram_id: int
    first_name: str | None
    username: str | None
    is_admin: bool
    rating: Decimal


class JobCreate(BaseModel):
    public_text: str = Field(min_length=1, max_length=4000)
    full_text: str = Field(min_length=1, max_length=10000)


class JobResponse(BaseModel):
    id: int
    public_text: str
    full_text: str | None = None
    status: JobStatus
    created_at: datetime
    closed_at: datetime | None
    final_amount: int | None
    assignee_name: str | None = None
    comment_text: str | None = None
    comment_created_at: datetime | None = None
    comment_updated_at: datetime | None = None

class CommentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

class CompleteRequest(BaseModel):
    amount: int = Field(ge=0, le=2_000_000_000)


class AddUserRequest(BaseModel):
    telegram_id: int


class UserResponse(BaseModel):
    telegram_id: int
    first_name: str | None
    username: str | None
    is_admin: bool
    is_active: bool
    rating: Decimal
    active_jobs: int
    completed_jobs: int
