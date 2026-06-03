from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.artifact import ArtifactResponse
from app.schemas.character import CharacterAssignmentResponse, CharacterResponse
from app.schemas.dub import DubSegmentResponse
from app.schemas.job import JobResponse
from app.schemas.speaker import SpeakerSegmentResponse
from app.schemas.timeline import TimelineClipResponse
from app.schemas.translation import TranslationSegmentResponse
from app.schemas.transcript import TranscriptSegmentResponse


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    source_language: str | None = None
    target_language: str = "tr"


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    source_language: str | None
    target_language: str
    status: str
    storage_key: str
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class ProjectEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    entity_type: str
    entity_id: str | None
    payload_json: dict
    created_at: datetime


class ProjectDetailResponse(ProjectListItem):
    artifacts: list[ArtifactResponse] = Field(default_factory=list)
    jobs: list[JobResponse] = Field(default_factory=list)
    events: list[ProjectEventResponse] = Field(default_factory=list)
    characters: list[CharacterResponse] = Field(default_factory=list)
    character_assignments: list[CharacterAssignmentResponse] = Field(default_factory=list)
    transcript_segments: list[TranscriptSegmentResponse] = Field(default_factory=list)
    speaker_segments: list[SpeakerSegmentResponse] = Field(default_factory=list)
    translation_segments: list[TranslationSegmentResponse] = Field(default_factory=list)
    dub_segments: list[DubSegmentResponse] = Field(default_factory=list)
    timeline_clips: list[TimelineClipResponse] = Field(default_factory=list)
