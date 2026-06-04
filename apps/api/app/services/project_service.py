from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.project import Project, ProjectMember
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.dub_repository import DubRepository
from app.repositories.project_event_repository import ProjectEventRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.translation_repository import TranslationRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.repositories.voice_profile_repository import VoiceProfileRepository
from app.schemas.artifact import ArtifactResponse
from app.schemas.character import CharacterAssignmentResponse, CharacterResponse
from app.schemas.dub import DubSegmentResponse
from app.schemas.job import JobResponse
from app.schemas.speaker import SpeakerSegmentResponse
from app.schemas.timeline import TimelineClipResponse
from app.schemas.project import ProjectCreateRequest, ProjectDetailResponse, ProjectListItem, ProjectEventResponse
from app.schemas.translation import TranslationSegmentResponse
from app.schemas.transcript import TranscriptSegmentResponse
from app.schemas.voice_profile import VoiceProfileResponse
from app.services.event_service import EventService


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.characters = CharacterRepository(db)
        self.dubs = DubRepository(db)
        self.events = ProjectEventRepository(db)
        self.transcripts = TranscriptRepository(db)
        self.speakers = SpeakerRepository(db)
        self.translations = TranslationRepository(db)
        self.voice_profiles = VoiceProfileRepository(db)
        self.event_service = EventService(db)

    def list_for_user(self, user_id: str) -> list[ProjectListItem]:
        return [ProjectListItem.model_validate(item) for item in self.projects.list_for_user(user_id)]

    def create(self, payload: ProjectCreateRequest, current_user) -> ProjectDetailResponse:
        project_id = str(uuid7())
        project = Project(
            id=project_id,
            name=payload.name,
            description=payload.description,
            source_language=payload.source_language,
            target_language=payload.target_language,
            storage_key=f"project_{project_id}",
            created_by_user_id=current_user.id,
        )
        self.projects.create(project)
        self.projects.add_member(
            ProjectMember(
                id=str(uuid7()),
                project_id=project.id,
                user_id=current_user.id,
                role=current_user.role,
            )
        )
        self.event_service.publish_audit(
            project_id=project.id,
            actor_user_id=current_user.id,
            entity_type="project",
            entity_id=project.id,
            event_type=EventType.PROJECT_CREATED.value,
            payload_json={"name": project.name},
        )
        self.db.commit()
        self.db.refresh(project)
        return self.get_detail(project.id, current_user.id)

    def get_detail(self, project_id: str, user_id: str) -> ProjectDetailResponse:
        if not self.projects.user_has_access(project_id, user_id):
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

        links = self.artifacts.list_links_for_project(project_id)
        parent_map: dict[str, list[str]] = {}
        for link in links:
            parent_map.setdefault(str(link.child_artifact_id), []).append(str(link.parent_artifact_id))

        voice_assignments = {item.character_id: item for item in self.voice_profiles.list_assignments_for_project(project_id)}
        character_responses: list[CharacterResponse] = []
        for item in project.characters:
            assignment = voice_assignments.get(item.id)
            character_responses.append(
                CharacterResponse(
                    **CharacterResponse.model_validate(item).model_dump(
                        exclude={"assigned_voice_profile_id", "assigned_voice_profile"}
                    ),
                    assigned_voice_profile_id=assignment.voice_profile_id if assignment else None,
                    assigned_voice_profile=(
                        VoiceProfileResponse.model_validate(assignment.voice_profile)
                        if assignment and assignment.voice_profile
                        else None
                    ),
                )
            )

        return ProjectDetailResponse(
            **ProjectListItem.model_validate(project).model_dump(),
            artifacts=[
                ArtifactResponse(
                    **ArtifactResponse.model_validate(item).model_dump(exclude={"parent_artifact_ids"}),
                    parent_artifact_ids=parent_map.get(str(item.id), []),
                )
                for item in project.artifacts
            ],
            jobs=[JobResponse.model_validate(item) for item in project.jobs],
            events=[ProjectEventResponse.model_validate(item) for item in project.events],
            characters=character_responses,
            character_assignments=[CharacterAssignmentResponse.model_validate(item) for item in project.character_assignments],
            transcript_segments=[TranscriptSegmentResponse.model_validate(item) for item in project.transcript_segments],
            speaker_segments=[SpeakerSegmentResponse.model_validate(item) for item in project.speaker_segments],
            translation_segments=[TranslationSegmentResponse.model_validate(item) for item in project.translation_segments],
            dub_segments=[DubSegmentResponse.model_validate(item) for item in project.dub_segments],
            timeline_clips=[TimelineClipResponse.model_validate(item) for item in project.timeline_clips],
        )
