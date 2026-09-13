import logging
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_async_db
from app.config import settings

router = APIRouter(prefix="/health", tags=["Health"])
logger = logging.getLogger("health")


@router.get("")
async def health_check(db: AsyncSession = Depends(get_async_db)):
    """Comprehensive health check verifying FastAPI server, database connectivity, and PostGIS status."""
    db_connected = False
    postgis_version = "Not Available"
    aoi_count = 0
    scene_count = 0
    infra_count = 0

    try:
        # Check PostGIS extension
        result = await db.execute(text("SELECT PostGIS_Full_Version();"))
        row = result.scalar_one_or_none()
        if row:
            db_connected = True
            postgis_version = str(row)

        # Query basic counts
        aoi_res = await db.execute(text("SELECT COUNT(*) FROM aois;"))
        aoi_count = aoi_res.scalar_one_or_none() or 0

        scene_res = await db.execute(text("SELECT COUNT(*) FROM satellite_scenes;"))
        scene_count = scene_res.scalar_one_or_none() or 0

        infra_res = await db.execute(text("SELECT COUNT(*) FROM infrastructure;"))
        infra_count = infra_res.scalar_one_or_none() or 0

    except Exception as e:
        logger.error(f"Healthcheck database error: {e}")
        db_connected = False

    return {
        "status": "healthy" if db_connected else "degraded",
        "service": "TerraLens Spatial Intelligence Engine",
        "version": "1.0.0-phase1",
        "environment": settings.ENVIRONMENT,
        "database": {
            "connected": db_connected,
            "postgis_version": postgis_version,
            "counts": {
                "aois": aoi_count,
                "satellite_scenes": scene_count,
                "infrastructure_features": infra_count,
            },
        },
        "gis_capabilities": {
            "postgis_spatial_engine": True if db_connected else False,
            "raster_ndvi_engine": "Ready (Phase 2)",
            "vector_spatial_overlay": "Ready (Phase 3)",
            "ai_agent_orchestrator": "Ready (Phase 4)",
        },
    }
