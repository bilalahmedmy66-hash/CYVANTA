from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.database.base import Base
from app.database.session import engine
from app.database.migrations import ensure_ai_analysis_job_retry_column
from app import models
from app.api import auth, assets, missions, executions, emergency_stops, asset_authorizations, organizations, intelligence_graph, ai, ai_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_ai_analysis_job_retry_column(engine)
    yield


app = FastAPI(
    title=settings.app_name,
    description="Autonomous Cyber Operations Platform",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(intelligence_graph.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(ai_jobs.router, prefix="/api/v1")
app.include_router(assets.router, prefix="/api/v1")
app.include_router(asset_authorizations.router, prefix="/api/v1")
app.include_router(missions.router)
app.include_router(executions.router)
app.include_router(emergency_stops.router, prefix="/api/v1")


@app.get("/", tags=["System"])
def root():
    return {
        "application": settings.app_name,
        "message": "CYVANTA backend is running.",
        "documentation": "/docs",
    }


@app.get("/api/v1/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/api/v1/system/info", tags=["System"])
def system_info():
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
    }
