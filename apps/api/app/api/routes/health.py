from fastapi import APIRouter

from app.core.openapi import COMMON_ERROR_RESPONSES
from app.schemas.health import DependencyHealthResponse, HealthResponse
from app.services.health_service import HealthService


router = APIRouter()


@router.get("/health", response_model=HealthResponse, responses=COMMON_ERROR_RESPONSES)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/db", response_model=DependencyHealthResponse, responses=COMMON_ERROR_RESPONSES)
def health_db() -> DependencyHealthResponse:
    HealthService().check_db()
    return DependencyHealthResponse(status="ok", dependency="db")


@router.get("/health/redis", response_model=DependencyHealthResponse, responses=COMMON_ERROR_RESPONSES)
def health_redis() -> DependencyHealthResponse:
    HealthService().check_redis()
    return DependencyHealthResponse(status="ok", dependency="redis")
