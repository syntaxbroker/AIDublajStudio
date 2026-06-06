from pydantic import BaseModel


class ProviderStatusItem(BaseModel):
    capability: str
    provider: str
    is_mock: bool


class ProviderStatusResponse(BaseModel):
    allow_mock_providers: bool
    has_mock_provider: bool
    providers: list[ProviderStatusItem]
    warning: str | None = None


class ProjectDurationItem(BaseModel):
    artifact_id: str
    artifact_type: str
    duration_ms: int | None
    storage_path: str


class ProjectDurationReportResponse(BaseModel):
    project_id: str
    max_timeline_end_ms: int | None
    active_providers: ProviderStatusResponse
    artifacts: list[ProjectDurationItem]
