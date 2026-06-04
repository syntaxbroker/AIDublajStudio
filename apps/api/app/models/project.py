from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import EventType, ProjectStatus, UserRole
from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    source_language: Mapped[str | None] = mapped_column(String(16))
    target_language: Mapped[str] = mapped_column(String(16), server_default="tr")
    status: Mapped[ProjectStatus] = mapped_column(Enum(ProjectStatus, name="project_status", create_type=False), server_default="ACTIVE")
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_by_user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    members = relationship("ProjectMember", back_populates="project")
    artifacts = relationship("Artifact", back_populates="project", order_by="Artifact.created_at.desc()")
    jobs = relationship("Job", back_populates="project", order_by="Job.created_at.desc()")
    events = relationship("ProjectEvent", back_populates="project", order_by="ProjectEvent.created_at.desc()")
    transcript_segments = relationship("TranscriptSegment", back_populates="project", order_by="TranscriptSegment.start_ms.asc()")
    speaker_segments = relationship("SpeakerSegment", back_populates="project", order_by="SpeakerSegment.start_ms.asc()")
    translation_segments = relationship("TranslationSegment", back_populates="project", order_by="TranslationSegment.created_at.asc()")
    dub_segments = relationship("DubSegment", back_populates="project", order_by="DubSegment.created_at.asc()")
    timeline_clips = relationship("TimelineClip", back_populates="project", order_by="TimelineClip.start_ms.asc()")
    characters = relationship("Character", back_populates="project", order_by="Character.created_at.asc()")
    character_assignments = relationship("CharacterAssignment", back_populates="project", order_by="CharacterAssignment.created_at.asc()")
    character_voice_assignments = relationship("CharacterVoiceAssignment", order_by="CharacterVoiceAssignment.created_at.asc()")


class ProjectMember(Base):
    __tablename__ = "project_members"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role", create_type=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    project = relationship("Project", back_populates="members")


class ProjectEvent(Base):
    __tablename__ = "project_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    actor_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    related_job_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    event_type: Mapped[EventType] = mapped_column(Enum(EventType, name="event_type", create_type=False))
    payload_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    project = relationship("Project", back_populates="events")
