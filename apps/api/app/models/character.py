from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    project = relationship("Project", back_populates="characters")


class CharacterAssignment(Base):
    __tablename__ = "character_assignments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    character_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("characters.id", ondelete="CASCADE"))
    speaker_label: Mapped[str | None] = mapped_column(String(64))
    transcript_segment_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("transcript_segments.id", ondelete="CASCADE"))
    timeline_clip_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("timeline_clips.id", ondelete="CASCADE"))
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    assignment_source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    project = relationship("Project", back_populates="character_assignments")
