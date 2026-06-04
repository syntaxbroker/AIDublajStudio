from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SegmentStatus
from app.db.base import Base


class DubSegment(Base):
    __tablename__ = "dub_segments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    translation_segment_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("translation_segments.id", ondelete="SET NULL"))
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    project_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("project_versions.id", ondelete="SET NULL"))
    voice_profile_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("voice_profiles.id", ondelete="SET NULL"))
    tts_artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="SET NULL"))
    timeline_clip_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("timeline_clips.id", ondelete="SET NULL"))
    character_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("characters.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)
    audio_artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    similarity_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    duration_match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    emotion_match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    overall_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    regen_count: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[SegmentStatus] = mapped_column(Enum(SegmentStatus, name="segment_status", create_type=False), server_default="DRAFT")
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    project = relationship("Project", back_populates="dub_segments")
