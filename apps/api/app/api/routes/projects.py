from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.character import CharacterRenameRequest
from app.schemas.project import ProjectCreateRequest, ProjectDetailResponse, ProjectListItem
from app.schemas.timeline import TimelineClipMergeRequest, TimelineClipSplitRequest, TimelineClipUpdateRequest, TimelineResponse
from app.schemas.voice_profile import CharacterVoiceAssignmentRequest
from app.services.character_service import CharacterService
from app.services.diarization_service import DiarizationService
from app.services.project_service import ProjectService
from app.services.audio_mix_service import AudioMixService
from app.services.timeline_service import TimelineService
from app.services.render_service import RenderService
from app.services.tts_service import TTSService
from app.services.translation_service import TranslationService
from app.services.voice_sample_service import VoiceSampleService
from app.services.voice_profile_service import VoiceProfileService


router = APIRouter()


@router.get("", response_model=list[ProjectListItem], responses=COMMON_ERROR_RESPONSES)
def list_projects(db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> list[ProjectListItem]:
    return ProjectService(db).list_for_user(current_user.id)


@router.post("", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    return ProjectService(db).create(payload, current_user)


@router.get("/{project_id}", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    return ProjectService(db).get_detail(project_id, current_user.id)


@router.post("/{project_id}/translate", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def translate_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    TranslationService(db).create_job_for_project(project_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post("/{project_id}/tts", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def tts_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    TTSService(db).create_job_for_project(project_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post("/{project_id}/audio-mix", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def audio_mix_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    AudioMixService(db).create_job_for_project(project_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post("/{project_id}/render", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def render_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    RenderService(db).create_job_for_project(project_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post("/{project_id}/diarize", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def diarize_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    project = service.projects.get_by_id(project_id)
    if not project:
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    proxy_artifact = next(
        (
            artifact
            for artifact in project.artifacts
            if getattr(artifact.artifact_type, "value", str(artifact.artifact_type)) == "PROXY_VIDEO"
        ),
        None,
    )
    if not proxy_artifact:
        raise AppError("DIARIZATION_SOURCE_NOT_FOUND", "Proxy video not found", 404)
    DiarizationService(db).create_job_for_project(project_id, current_user.id, proxy_artifact.id)
    return service.get_detail(project_id, current_user.id)


@router.post("/{project_id}/characters/from-speakers", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def create_characters_from_speakers(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    CharacterService(db).create_from_speakers(project_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.patch("/{project_id}/characters/{character_id}", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def rename_character(
    project_id: str,
    character_id: str,
    payload: CharacterRenameRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    CharacterService(db).rename_character(project_id, character_id, payload, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post(
    "/{project_id}/characters/{character_id}/voice-profile",
    response_model=ProjectDetailResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def assign_voice_profile_to_character(
    project_id: str,
    character_id: str,
    payload: CharacterVoiceAssignmentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    VoiceProfileService(db).assign_to_character(project_id, character_id, payload, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post(
    "/{project_id}/characters/{character_id}/voice-sample",
    response_model=ProjectDetailResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def extract_character_voice_sample(
    project_id: str,
    character_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    VoiceSampleService(db).create_job_for_character(project_id, character_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.post(
    "/{project_id}/characters/{character_id}/voice-profile/from-sample",
    response_model=ProjectDetailResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def create_voice_profile_from_sample(
    project_id: str,
    character_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    VoiceProfileService(db).create_profile_from_sample(project_id, character_id, current_user.id)
    return service.get_detail(project_id, current_user.id)


@router.get("/{project_id}/timeline", response_model=TimelineResponse, responses=COMMON_ERROR_RESPONSES)
def get_timeline(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> TimelineResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    return TimelineService(db).get_timeline(project_id)


@router.patch("/{project_id}/timeline/clips/{clip_id}", response_model=TimelineResponse, responses=COMMON_ERROR_RESPONSES)
def update_timeline_clip(
    project_id: str,
    clip_id: str,
    payload: TimelineClipUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> TimelineResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    return TimelineService(db).update_clip(project_id, clip_id, payload, current_user.id)


@router.post("/{project_id}/timeline/clips/{clip_id}/split", response_model=TimelineResponse, responses=COMMON_ERROR_RESPONSES)
def split_timeline_clip(
    project_id: str,
    clip_id: str,
    payload: TimelineClipSplitRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> TimelineResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    return TimelineService(db).split_clip(project_id, clip_id, payload, current_user.id)


@router.post("/{project_id}/timeline/clips/merge", response_model=TimelineResponse, responses=COMMON_ERROR_RESPONSES)
def merge_timeline_clips(
    project_id: str,
    payload: TimelineClipMergeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> TimelineResponse:
    service = ProjectService(db)
    if not service.projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
    return TimelineService(db).merge_clips(project_id, payload, current_user.id)
