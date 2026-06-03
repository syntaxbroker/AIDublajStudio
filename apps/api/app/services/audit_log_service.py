from sqlalchemy.orm import Session

from app.core.uuid7 import uuid7
from app.models.project import ProjectEvent
from app.repositories.project_event_repository import ProjectEventRepository


class AuditLogService:
    def __init__(self, db: Session) -> None:
        self.events = ProjectEventRepository(db)

    def persist(
        self,
        *,
        event_type: str,
        entity_type: str,
        project_id: str | None = None,
        actor_user_id: str | None = None,
        entity_id: str | None = None,
        related_job_id: str | None = None,
        payload_json: dict | None = None,
    ) -> ProjectEvent:
        event = ProjectEvent(
            id=str(uuid7()),
            project_id=project_id,
            actor_user_id=actor_user_id,
            related_job_id=related_job_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload_json=payload_json or {},
        )
        self.events.create(event)
        return event
