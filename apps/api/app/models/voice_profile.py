from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64))
    voice_id: Mapped[str] = mapped_column(String(255))
    profile_type: Mapped[str] = mapped_column(String(32), server_default="edge_tts")
    language: Mapped[str] = mapped_column(String(16), server_default="tr")
    gender: Mapped[str | None] = mapped_column(String(32))
    reference_audio_artifact_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="SET NULL"))
    source_character_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("characters.id", ondelete="SET NULL"))
    source_speaker_label: Mapped[str | None] = mapped_column(String(64))
    sample_duration_ms: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    is_shared: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    status: Mapped[str] = mapped_column(String(32), server_default="ready")
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))


class CharacterVoiceAssignment(Base):
    __tablename__ = "character_voice_assignments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    character_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("characters.id", ondelete="CASCADE"))
    voice_profile_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("voice_profiles.id", ondelete="CASCADE"))
    assignment_source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))

    voice_profile = relationship("VoiceProfile")
