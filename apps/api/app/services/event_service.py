from sqlalchemy.orm import Session

from app.core.event_bus import AuditEnvelope, publish_event
from app.services.audit_log_service import AuditLogService


class EventService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def publish_audit(
        self,
        *,
        event_type: str,
        entity_type: str,
        project_id: str | None = None,
        actor_user_id: str | None = None,
        entity_id: str | None = None,
        related_job_id: str | None = None,
        payload_json: dict | None = None,
    ) -> None:
        if self.db is not None:
            AuditLogService(self.db).persist(
                event_type=event_type,
                entity_type=entity_type,
                project_id=project_id,
                actor_user_id=actor_user_id,
                entity_id=entity_id,
                related_job_id=related_job_id,
                payload_json=payload_json or {},
            )
            return

        publish_event(
            AuditEnvelope(
                event_type=event_type,
                entity_type=entity_type,
                project_id=project_id,
                actor_user_id=actor_user_id,
                entity_id=entity_id,
                related_job_id=related_job_id,
                payload_json=payload_json or {},
            )
        )
