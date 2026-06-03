from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class AuditEnvelope:
    event_type: str
    entity_type: str
    project_id: str | None = None
    actor_user_id: str | None = None
    entity_id: str | None = None
    related_job_id: str | None = None
    payload_json: dict = field(default_factory=dict)


_audit_events: ContextVar[list[AuditEnvelope]] = ContextVar("audit_events", default=[])


def reset_events() -> None:
    _audit_events.set([])


def publish_event(event: AuditEnvelope) -> None:
    current = list(_audit_events.get())
    current.append(event)
    _audit_events.set(current)


def pop_events() -> list[AuditEnvelope]:
    events = list(_audit_events.get())
    _audit_events.set([])
    return events
