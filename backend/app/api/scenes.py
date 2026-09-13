import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_async_db

router = APIRouter(prefix="/scenes", tags=["Satellite Scenes"])


@router.get("")
async def list_scenes(
    aoi_id: Optional[uuid.UUID] = Query(None, description="Filter by AOI ID"),
    db: AsyncSession = Depends(get_async_db),
):
    """List all available satellite scenes with metadata."""
    if aoi_id:
        query = text(
            """
            SELECT s.*, a.name as aoi_name 
            FROM satellite_scenes s
            JOIN aois a ON s.aoi_id = a.id
            WHERE s.aoi_id = :aoi_id
            ORDER BY s.acquisition_date DESC;
            """
        )
        result = await db.execute(query, {"aoi_id": aoi_id})
    else:
        query = text(
            """
            SELECT s.*, a.name as aoi_name 
            FROM satellite_scenes s
            JOIN aois a ON s.aoi_id = a.id
            ORDER BY s.acquisition_date DESC;
            """
        )
        result = await db.execute(query)

    rows = result.fetchall()
    scenes = []
    for row in rows:
        scenes.append(
            {
                "id": str(row.id),
                "aoi_id": str(row.aoi_id),
                "aoi_name": row.aoi_name,
                "scene_identifier": row.scene_identifier,
                "satellite": row.satellite,
                "sensor": row.sensor,
                "acquisition_date": row.acquisition_date.isoformat(),
                "cloud_cover": float(row.cloud_cover),
                "spatial_resolution": float(row.spatial_resolution),
                "raster_path": row.raster_path,
                "red_band_path": row.red_band_path,
                "nir_band_path": row.nir_band_path,
                "swir_band_path": row.swir_band_path,
                "metadata": row.metadata,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"count": len(scenes), "scenes": scenes}


@router.get("/{scene_id}")
async def get_scene(scene_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)):
    """Get single scene details by ID."""
    query = text(
        """
        SELECT s.*, a.name as aoi_name 
        FROM satellite_scenes s
        JOIN aois a ON s.aoi_id = a.id
        WHERE s.id = :scene_id;
        """
    )
    result = await db.execute(query, {"scene_id": scene_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Scene not found")

    return {
        "id": str(row.id),
        "aoi_id": str(row.aoi_id),
        "aoi_name": row.aoi_name,
        "scene_identifier": row.scene_identifier,
        "satellite": row.satellite,
        "sensor": row.sensor,
        "acquisition_date": row.acquisition_date.isoformat(),
        "cloud_cover": float(row.cloud_cover),
        "spatial_resolution": float(row.spatial_resolution),
        "raster_path": row.raster_path,
        "red_band_path": row.red_band_path,
        "nir_band_path": row.nir_band_path,
        "swir_band_path": row.swir_band_path,
        "metadata": row.metadata,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
