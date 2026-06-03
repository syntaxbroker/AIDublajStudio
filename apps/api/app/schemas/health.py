from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class DependencyHealthResponse(BaseModel):
    status: str
    dependency: str
