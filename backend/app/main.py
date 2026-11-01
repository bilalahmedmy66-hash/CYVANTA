from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.database.base import Base
from app.database.session import engine
from app import models
from app.api import auth, assets, missions


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
app.include_router(assets.router, prefix="/api/v1")
app.include_router(missions.router)


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
