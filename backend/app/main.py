import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.health import router as health_router
from app.api.aois import router as aois_router
from app.api.scenes import router as scenes_router
from app.api.infrastructure import router as infra_router
from app.api.analysis import router as analysis_router

# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("terralens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("TerraLens Spatial Intelligence Engine starting up...")
    logger.info(f"Environment: {settings.ENVIRONMENT} | Debug: {settings.DEBUG}")
    yield
    logger.info("TerraLens Spatial Intelligence Engine shutting down...")


app = FastAPI(
    title="TerraLens API",
    description="AI-Powered Satellite & Spatial Intelligence Engine with PostGIS and Remote Sensing Analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(health_router, prefix="/api")
app.include_router(aois_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(infra_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")



@app.get("/")
async def root():
    return {
        "app": "TerraLens Spatial Intelligence API",
        "status": "online",
        "docs_url": "/docs",
        "health_url": "/api/health",
    }
