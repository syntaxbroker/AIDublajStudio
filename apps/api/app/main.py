from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

import app.models  # noqa: F401
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.event_bus import pop_events, reset_events
from app.db.session import close_engine
from app.db.session import SessionLocal
from app.schemas.common import ApiErrorResponse
from app.services.audit_log_service import AuditLogService
from app.services.bootstrap_service import BootstrapService


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    openapi_url=f"{settings.api_prefix}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        reset_events()
        try:
            response = await call_next(request)
        finally:
            events = pop_events()
            if events:
                with SessionLocal() as db:
                    audit = AuditLogService(db)
                    for event in events:
                        audit.persist(
                            event_type=event.event_type,
                            entity_type=event.entity_type,
                            project_id=event.project_id,
                            actor_user_id=event.actor_user_id,
                            entity_id=event.entity_id,
                            related_job_id=event.related_job_id,
                            payload_json=event.payload_json,
                        )
                    db.commit()
        return response


app.add_middleware(AuditMiddleware)
app.include_router(api_router, prefix=settings.api_prefix)


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    body = ApiErrorResponse(error={"code": code, "message": message})
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response("VALIDATION_ERROR", str(exc.errors()), 422)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "HTTP_ERROR"
    if exc.status_code == 404:
        code = "ROUTE_NOT_FOUND"
    elif exc.status_code == 405:
        code = "METHOD_NOT_ALLOWED"
    return error_response(code, str(exc.detail), exc.status_code)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return error_response("INTERNAL_SERVER_ERROR", "Internal server error", 500)


@app.on_event("startup")
def on_startup() -> None:
    bootstrap = BootstrapService()
    bootstrap.ensure_default_users()
    bootstrap.ensure_default_voice_profiles()


@app.on_event("shutdown")
def on_shutdown() -> None:
    close_engine()
