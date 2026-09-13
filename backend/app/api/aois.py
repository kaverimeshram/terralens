import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_async_db

router = APIRouter(prefix="/aois", tags=["AOIs"])


@router.get("")
async def list_aois(
    format: Optional[str] = Query("geojson", description="Response format: 'geojson' or 'json'"),
    db: AsyncSession = Depends(get_async_db),
):
    """List all configured study areas (AOIs).

    Supports GeoJSON FeatureCollection output ready for direct MapLibre GL rendering.
    """
    query = text(
        """
        SELECT 
            id, 
            name, 
            description, 
            bounding_box,
            created_at,
            ST_AsGeoJSON(geometry) as geojson_geom,
            ST_Area(geometry::geography) / 10000.0 as area_hectares
        FROM aois
        ORDER BY name;
        """
    )
    result = await db.execute(query)
    rows = result.fetchall()

    if format == "geojson":
        features = []
        for row in rows:
            features.append(
                {
                    "type": "Feature",
                    "id": str(row.id),
                    "geometry": json.loads(row.geojson_geom),
                    "properties": {
                        "id": str(row.id),
                        "name": row.name,
                        "description": row.description,
                        "bounding_box": row.bounding_box,
                        "area_hectares": round(float(row.area_hectares), 2) if row.area_hectares else 0.0,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    },
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    # JSON format fallback
    items = []
    for row in rows:
        items.append(
            {
                "id": str(row.id),
                "name": row.name,
                "description": row.description,
                "bounding_box": row.bounding_box,
                "area_hectares": round(float(row.area_hectares), 2) if row.area_hectares else 0.0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"aois": items}


@router.get("/{aoi_id}")
async def get_aoi(aoi_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)):
    """Retrieve detailed metadata and boundary for a specific AOI."""
    query = text(
        """
        SELECT 
            id, 
            name, 
            description, 
            bounding_box,
            created_at,
            ST_AsGeoJSON(geometry) as geojson_geom,
            ST_Area(geometry::geography) / 10000.0 as area_hectares
        FROM aois
        WHERE id = :aoi_id;
        """
    )
    result = await db.execute(query, {"aoi_id": aoi_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="AOI not found")

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "bounding_box": row.bounding_box,
        "area_hectares": round(float(row.area_hectares), 2) if row.area_hectares else 0.0,
        "geometry": json.loads(row.geojson_geom),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/{aoi_id}/scenes")
async def get_aoi_scenes(aoi_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)):
    """Retrieve all satellite scenes cataloged for a specific AOI."""
    query = text(
        """
        SELECT 
            id, 
            scene_identifier, 
            satellite, 
            sensor, 
            acquisition_date, 
            cloud_cover, 
            spatial_resolution, 
            raster_path, 
            metadata, 
            created_at
        FROM satellite_scenes
        WHERE aoi_id = :aoi_id
        ORDER BY acquisition_date ASC;
        """
    )
    result = await db.execute(query, {"aoi_id": aoi_id})
    rows = result.fetchall()

    scenes = []
    for row in rows:
        scenes.append(
            {
                "id": str(row.id),
                "scene_identifier": row.scene_identifier,
                "satellite": row.satellite,
                "sensor": row.sensor,
                "acquisition_date": row.acquisition_date.isoformat(),
                "cloud_cover": float(row.cloud_cover),
                "spatial_resolution": float(row.spatial_resolution),
                "raster_path": row.raster_path,
                "metadata": row.metadata,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"aoi_id": str(aoi_id), "count": len(scenes), "scenes": scenes}


@router.get("/{aoi_id}/infrastructure")
async def get_aoi_infrastructure(aoi_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)):
    """Retrieve all infrastructure features intersecting or belonging to an AOI in GeoJSON format."""
    query = text(
        """
        SELECT 
            i.id, 
            i.name, 
            i.type, 
            i.metadata, 
            ST_AsGeoJSON(i.geometry) as geojson_geom
        FROM infrastructure i
        JOIN aois a ON (i.aoi_id = a.id OR ST_Intersects(i.geometry, a.geometry))
        WHERE a.id = :aoi_id
        ORDER BY i.name;
        """
    )
    result = await db.execute(query, {"aoi_id": aoi_id})
    rows = result.fetchall()

    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "id": str(row.id),
                "geometry": json.loads(row.geojson_geom),
                "properties": {
                    "id": str(row.id),
                    "name": row.name,
                    "type": row.type,
                    "metadata": row.metadata,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "aoi_id": str(aoi_id),
        "features": features,
    }


@router.get("/{aoi_id}/population")
async def get_aoi_population_zones(aoi_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)):
    """Retrieve population zones for an AOI in GeoJSON format."""
    query = text(
        """
        SELECT 
            p.id, 
            p.name, 
            p.population, 
            p.metadata, 
            ST_AsGeoJSON(p.geometry) as geojson_geom,
            ST_Area(p.geometry::geography) / 10000.0 as area_hectares
        FROM population_zones p
        JOIN aois a ON (p.aoi_id = a.id OR ST_Intersects(p.geometry, a.geometry))
        WHERE a.id = :aoi_id
        ORDER BY p.population DESC;
        """
    )
    result = await db.execute(query, {"aoi_id": aoi_id})
    rows = result.fetchall()

    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "id": str(row.id),
                "geometry": json.loads(row.geojson_geom),
                "properties": {
                    "id": str(row.id),
                    "name": row.name,
                    "population": row.population,
                    "area_hectares": round(float(row.area_hectares), 2) if row.area_hectares else 0.0,
                    "metadata": row.metadata,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "aoi_id": str(aoi_id),
        "features": features,
    }
