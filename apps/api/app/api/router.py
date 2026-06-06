from fastapi import APIRouter

from app.api.routes import artifacts, auth, health, jobs, projects, runtime, uploads, voice_profiles


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(runtime.router, tags=["runtime"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(uploads.router, prefix="/projects", tags=["uploads"])
api_router.include_router(artifacts.router, prefix="/projects", tags=["artifacts"])
api_router.include_router(voice_profiles.router, prefix="/voice-profiles", tags=["voice-profiles"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
