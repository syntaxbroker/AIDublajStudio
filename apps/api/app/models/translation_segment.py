from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SegmentStatus
from app.db.base import Base


class TranslationSegment(Base):
    __tablename__ = "translation_segments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    transcript_segment_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("transcript_segments.id", ondelete="CASCADE"))
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    project_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("project_versions.id", ondelete="SET NULL"))
    provider_config_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("provider_configs.id", ondelete="SET NULL"))
    model_registry_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("model_registry.id", ondelete="SET NULL"))
    source_language: Mapped[str | None] = mapped_column(String(16))
    target_language: Mapped[str] = mapped_column(String(16), server_default="tr")
    source_text: Mapped[str | None] = mapped_column(Text)
    translated_text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(64))
    duration_target_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[SegmentStatus] = mapped_column(Enum(SegmentStatus, name="segment_status", create_type=False), server_default="DRAFT")
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    project = relationship("Project", back_populates="translation_segments")
