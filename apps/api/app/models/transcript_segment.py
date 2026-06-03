from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SegmentStatus, TranscriptSource
from app.db.base import Base


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    project_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("project_versions.id", ondelete="SET NULL"))
    source_artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="SET NULL"))
    segment_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    speaker_label: Mapped[str | None] = mapped_column(String(64))
    language_code: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    source: Mapped[TranscriptSource] = mapped_column(Enum(TranscriptSource, name="transcript_source", create_type=False), server_default="ASR")
    status: Mapped[SegmentStatus] = mapped_column(Enum(SegmentStatus, name="segment_status", create_type=False), server_default="DRAFT")
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    project = relationship("Project", back_populates="transcript_segments")
