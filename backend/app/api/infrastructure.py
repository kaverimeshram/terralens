import json
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_async_db

router = APIRouter(prefix="/infrastructure", tags=["Infrastructure"])


@router.get("")
async def list_infrastructure(
    aoi_id: Optional[uuid.UUID] = Query(None, description="Filter by AOI ID"),
    type: Optional[str] = Query(None, description="Filter by infrastructure type"),
    format: Optional[str] = Query("geojson", description="Response format: 'geojson' or 'json'"),
    db: AsyncSession = Depends(get_async_db),
):
    """Retrieve infrastructure features with optional filtering and GeoJSON formatting."""
    filters = []
    params = {}

    if aoi_id:
        filters.append("aoi_id = :aoi_id")
        params["aoi_id"] = aoi_id
    if type:
        filters.append("type = :type")
        params["type"] = type

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    query_str = f"""
        SELECT 
            id, 
            aoi_id, 
            name, 
            type, 
            metadata, 
            ST_AsGeoJSON(geometry) as geojson_geom,
            created_at
        FROM infrastructure
        {where_clause}
        ORDER BY name;
    """

    result = await db.execute(text(query_str), params)
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
                        "aoi_id": str(row.aoi_id) if row.aoi_id else None,
                        "name": row.name,
                        "type": row.type,
                        "metadata": row.metadata,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    },
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    items = []
    for row in rows:
        items.append(
            {
                "id": str(row.id),
                "aoi_id": str(row.aoi_id) if row.aoi_id else None,
                "name": row.name,
                "type": row.type,
                "metadata": row.metadata,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"count": len(items), "infrastructure": items}


@router.get("/nearby")
async def find_nearby_infrastructure(
    lon: float = Query(..., description="Longitude (WGS84 EPSG:4326)"),
    lat: float = Query(..., description="Latitude (WGS84 EPSG:4326)"),
    radius_meters: float = Query(5000.0, description="Search radius in meters"),
    db: AsyncSession = Depends(get_async_db),
):
    """PostGIS ST_DWithin and ST_Distance spatial proximity search.

    Finds all infrastructure within `radius_meters` of a given geographic coordinate.
    """
    query = text(
        """
        SELECT 
            id, 
            name, 
            type, 
            metadata, 
            ST_AsGeoJSON(geometry) as geojson_geom,
            ST_Distance(
                geometry::geography, 
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            ) as distance_meters
        FROM infrastructure
        WHERE ST_DWithin(
            geometry::geography, 
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 
            :radius_meters
        )
        ORDER BY distance_meters ASC;
        """
    )
    result = await db.execute(query, {"lon": lon, "lat": lat, "radius_meters": radius_meters})
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
                    "distance_meters": round(float(row.distance_meters), 1),
                    "metadata": row.metadata,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "query_point": {"lon": lon, "lat": lat},
        "radius_meters": radius_meters,
        "count": len(features),
        "features": features,
    }
