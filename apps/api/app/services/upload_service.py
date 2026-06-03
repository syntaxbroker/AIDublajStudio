from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.enums import ArtifactType, EventType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.project_repository import ProjectRepository
from app.services.event_service import EventService
from app.services.job_service import JobService
from app.services.project_service import ProjectService
from app.services.storage_service import StorageService


class UploadService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.events = EventService(db)
        self.jobs = JobService(db)
        self.storage = StorageService()
        self.project_service = ProjectService(db)

    def upload_source_video(self, project_id: str, file: UploadFile, current_user):
        if not self.projects.user_has_access(project_id, current_user.id):
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        if not file.filename:
            raise AppError("FILE_NAME_REQUIRED", "File name is required", 400)

        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

        artifact_id = str(uuid7())
        self.events.publish_audit(
            project_id=project.id,
            actor_user_id=current_user.id,
            entity_type="upload",
            entity_id=artifact_id,
            event_type=EventType.UPLOAD_STARTED.value,
            payload_json={"file_name": file.filename},
        )
        relative_path, size_bytes, checksum = self.storage.save_source_video(project.storage_key, file, artifact_id)
        duplicate = self.artifacts.get_by_checksum(project.id, ArtifactType.SOURCE_VIDEO.value, checksum)
        if duplicate:
            self.storage.delete_relative_path(relative_path)
            raise AppError("DUPLICATE_ARTIFACT", "An identical source video already exists in this project", 409)

        artifact = Artifact(
            id=artifact_id,
            project_id=project.id,
            artifact_type=ArtifactType.SOURCE_VIDEO,
            storage_path=relative_path,
            file_name=file.filename,
            mime_type=file.content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum,
        )
        self.artifacts.create(artifact)
        self.events.publish_audit(
            project_id=project.id,
            actor_user_id=current_user.id,
            entity_type="artifact",
            entity_id=artifact.id,
            event_type=EventType.VIDEO_UPLOADED.value,
            payload_json={"artifact_type": artifact.artifact_type.value, "file_name": artifact.file_name},
        )
        job = self.jobs.create_ingest_job(project.id, current_user.id, artifact.id)
        self.db.commit()
        self.db.refresh(artifact)
        self.db.refresh(job)
        return self.project_service.get_detail(project.id, current_user.id)
