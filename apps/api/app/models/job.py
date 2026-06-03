from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import JobState, JobType
from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    project_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("project_versions.id", ondelete="SET NULL"))
    parent_job_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"))
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, name="job_type", create_type=False))
    state: Mapped[JobState] = mapped_column(Enum(JobState, name="job_state", create_type=False), server_default="PENDING")
    queue_name: Mapped[str] = mapped_column(String(64))
    worker_name: Mapped[str | None] = mapped_column(String(128))
    gpu_device_id: Mapped[int | None] = mapped_column(Integer)
    provider_config_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("provider_configs.id", ondelete="SET NULL"))
    model_registry_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("model_registry.id", ondelete="SET NULL"))
    priority: Mapped[int] = mapped_column(Integer, server_default="100")
    input_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_json: Mapped[dict | None] = mapped_column(JSONB)
    requested_by_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    project = relationship("Project", back_populates="jobs")
    attempts = relationship("JobAttempt", back_populates="job")


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    worker_name: Mapped[str | None] = mapped_column(String(128))
    state_from: Mapped[JobState | None] = mapped_column(Enum(JobState, name="job_state", create_type=False))
    state_to: Mapped[JobState] = mapped_column(Enum(JobState, name="job_state", create_type=False))
    log_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    job = relationship("Job", back_populates="attempts")
