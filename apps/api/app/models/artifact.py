from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ArtifactType
from app.db.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"))
    project_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("project_versions.id", ondelete="SET NULL"))
    created_by_job_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"))
    artifact_type: Mapped[ArtifactType] = mapped_column(Enum(ArtifactType, name="artifact_type", create_type=False))
    status: Mapped[str] = mapped_column(String(32), server_default="ACTIVE")
    storage_path: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    frame_rate: Mapped[float | None] = mapped_column(Numeric(8, 3))
    audio_channels: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    project = relationship("Project", back_populates="artifacts")


class ArtifactLink(Base):
    __tablename__ = "artifact_links"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    parent_artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="CASCADE"))
    child_artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("artifacts.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
