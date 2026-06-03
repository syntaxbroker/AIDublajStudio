from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ClipType
from app.db.base import Base


class TimelineClip(Base):
    __tablename__ = "timeline_clips"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    project_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("project_versions.id", ondelete="SET NULL"))
    transcript_segment_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("transcript_segments.id", ondelete="SET NULL"))
    translation_segment_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    dub_segment_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="SET NULL"))
    character_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("characters.id", ondelete="SET NULL"))
    edited_by_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    speaker_label: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(Text)
    translation_text: Mapped[str | None] = mapped_column(Text)
    clip_type: Mapped[ClipType] = mapped_column(Enum(ClipType, name="clip_type", create_type=False), server_default="DIALOG")
    track_index: Mapped[int] = mapped_column(Integer, server_default="0")
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    lane: Mapped[str] = mapped_column(String(32), server_default="dialog")
    is_locked: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    edit_version: Mapped[int] = mapped_column(Integer, server_default="0")
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    project = relationship("Project", back_populates="timeline_clips")
