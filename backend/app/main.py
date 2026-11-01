from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import settings


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class SystemInfoResponse(BaseModel):
    application: str
    version: str
    environment: str


app = FastAPI(
    title=settings.app_name,
    description="Autonomous Cyber Operations Platform",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/", tags=["System"])
def root():
    return {
        "application": settings.app_name,
        "message": "CYVANTA backend is running.",
        "documentation": "/docs",
    }


@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    tags=["System"],
)
def health_check():
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@app.get(
    "/api/v1/system/info",
    response_model=SystemInfoResponse,
    tags=["System"],
)
def system_info():
    return SystemInfoResponse(
        application=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )
