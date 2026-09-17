"""TerraLens Analysis API Endpoints.

Provides endpoints for:
- POST /api/analysis/ndvi-change: Execute deterministic remote sensing NDVI change analysis
- GET  /api/analysis/{analysis_id}/changes: Retrieve vectorized change polygons in GeoJSON format
- GET  /api/analysis/{analysis_id}: Retrieve analysis run metadata and metrics
- GET  /api/analysis: List past analysis runs
"""

import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_async_db
from app.gis.analysis_service import run_ndvi_change_analysis
from app.gis.validation import GISValidationError
from app.gis.spatial_service import (
    find_nearby_infrastructure,
    analyze_infrastructure_proximity,
    analyze_population_proximity,
    run_spatial_intersection,
    get_change_area_summary,
    validate_aoi_containment,
    get_analysis_spatial_summary,
)

router = APIRouter(prefix="/analysis", tags=["Analysis"])


class NDVIAnalysisRequest(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="Target Area of Interest UUID")
    before_scene_id: uuid.UUID = Field(..., description="Baseline (before) satellite scene UUID")
    after_scene_id: uuid.UUID = Field(..., description="Comparison (after) satellite scene UUID")
    threshold: float = Field(
        default=-0.20,
        description="NDVI difference threshold for significant vegetation decrease (default: -0.20)",
    )
    minimum_area_m2: float = Field(
        default=500.0,
        description="Minimum polygon area in m² to filter out single-pixel noise (default: 500.0 m²)",
    )


@router.post("/ndvi-change", status_code=status.HTTP_200_OK)
async def analyze_ndvi_change(
    payload: NDVIAnalysisRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Execute deterministic NDVI change detection between two satellite scenes.

    Calculates:
    - Before NDVI = (NIR - Red) / (NIR + Red)
    - After NDVI = (NIR - Red) / (NIR + Red)
    - NDVI Difference = After NDVI - Before NDVI
    - Significant Change Mask (difference <= threshold)
    - Geodesic metric polygonization and PostGIS storage
    """
    try:
        result = await run_ndvi_change_analysis(
            db=db,
            aoi_id=payload.aoi_id,
            before_scene_id=payload.before_scene_id,
            after_scene_id=payload.after_scene_id,
            threshold=payload.threshold,
            minimum_area_m2=payload.minimum_area_m2,
        )
        return result
    except GISValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GIS Validation Error: {str(e)}",
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Raster Asset Missing: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis Engine Error: {str(e)}",
        )


@router.get("/{analysis_id}/changes")
async def get_analysis_change_polygons(
    analysis_id: uuid.UUID,
    format: Optional[str] = Query("geojson", description="Response format: 'geojson'"),
    db: AsyncSession = Depends(get_async_db),
):
    """Retrieve vectorized change detection polygons for an analysis run in GeoJSON format.

    Ready for direct high-performance MapLibre GL rendering.
    """
    # Check analysis exists
    check_query = text("SELECT id, status, total_change_area_m2 FROM analysis_runs WHERE id = :id;")
    check_res = await db.execute(check_query, {"id": analysis_id})
    analysis_row = check_res.fetchone()
    if not analysis_row:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    poly_query = text(
        """
        SELECT 
            id, 
            analysis_run_id, 
            area_m2, 
            (area_m2 / 10000.0) as area_ha,
            change_value as mean_ndvi_change, 
            mean_before_ndvi, 
            mean_after_ndvi, 
            created_at,
            ST_AsGeoJSON(geometry) as geojson_geom
        FROM change_polygons
        WHERE analysis_run_id = :analysis_id
        ORDER BY area_m2 DESC;
        """
    )
    result = await db.execute(poly_query, {"analysis_id": analysis_id})
    rows = result.fetchall()

    features = []
    for row in rows:
        change_val = float(row.mean_ndvi_change) if row.mean_ndvi_change is not None else 0.0
        change_type = (
            "detected vegetation decrease"
            if change_val <= -0.20
            else "detected vegetation increase"
            if change_val >= 0.20
            else "unchanged"
        )
        features.append(
            {
                "type": "Feature",
                "id": str(row.id),
                "geometry": json.loads(row.geojson_geom),
                "properties": {
                    "id": str(row.id),
                    "analysis_run_id": str(row.analysis_run_id),
                    "change_type": change_type,
                    "area_m2": round(float(row.area_m2), 2),
                    "area_ha": round(float(row.area_ha), 4),
                    "mean_ndvi_change": round(change_val, 4),
                    "mean_before_ndvi": round(float(row.mean_before_ndvi), 4) if row.mean_before_ndvi is not None else None,
                    "mean_after_ndvi": round(float(row.mean_after_ndvi), 4) if row.mean_after_ndvi is not None else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "analysis_id": str(analysis_id),
        "count": len(features),
        "total_change_area_m2": round(float(analysis_row.total_change_area_m2 or 0.0), 2),
        "total_change_area_ha": round(float(analysis_row.total_change_area_m2 or 0.0) / 10000.0, 4),
        "features": features,
    }


@router.get("/{analysis_id}")
async def get_analysis_run(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Retrieve detailed metadata and execution summary for a specific analysis run."""
    query = text(
        """
        SELECT 
            r.id, 
            r.aoi_id, 
            a.name as aoi_name,
            r.before_scene_id, 
            s_before.scene_identifier as before_scene_identifier,
            s_before.acquisition_date as before_acquisition_date,
            r.after_scene_id, 
            s_after.scene_identifier as after_scene_identifier,
            s_after.acquisition_date as after_acquisition_date,
            r.analysis_type, 
            r.threshold, 
            r.ndvi_change, 
            r.total_change_area_m2, 
            (r.total_change_area_m2 / 10000.0) as total_change_area_ha,
            r.status, 
            r.validation_report, 
            r.activity_log, 
            r.created_at,
            (SELECT COUNT(*) FROM change_polygons WHERE analysis_run_id = r.id) as change_polygon_count
        FROM analysis_runs r
        JOIN aois a ON r.aoi_id = a.id
        JOIN satellite_scenes s_before ON r.before_scene_id = s_before.id
        JOIN satellite_scenes s_after ON r.after_scene_id = s_after.id
        WHERE r.id = :id;
        """
    )
    result = await db.execute(query, {"id": analysis_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    return {
        "id": str(row.id),
        "aoi_id": str(row.aoi_id),
        "aoi_name": row.aoi_name,
        "before_scene": {
            "id": str(row.before_scene_id),
            "scene_identifier": row.before_scene_identifier,
            "acquisition_date": row.before_acquisition_date.isoformat(),
        },
        "after_scene": {
            "id": str(row.after_scene_id),
            "scene_identifier": row.after_scene_identifier,
            "acquisition_date": row.after_acquisition_date.isoformat(),
        },
        "analysis_type": row.analysis_type,
        "threshold": float(row.threshold),
        "ndvi_change": float(row.ndvi_change) if row.ndvi_change is not None else None,
        "total_change_area_m2": float(row.total_change_area_m2) if row.total_change_area_m2 is not None else 0.0,
        "total_change_area_ha": float(row.total_change_area_ha) if row.total_change_area_ha is not None else 0.0,
        "change_polygon_count": int(row.change_polygon_count),
        "status": row.status,
        "validation_report": row.validation_report,
        "activity_log": row.activity_log,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_analysis_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
):
    """List recent analysis runs."""
    query = text(
        """
        SELECT 
            r.id, 
            r.aoi_id, 
            a.name as aoi_name,
            r.analysis_type, 
            r.threshold, 
            r.ndvi_change, 
            r.total_change_area_m2, 
            (r.total_change_area_m2 / 10000.0) as total_change_area_ha,
            r.status, 
            r.created_at,
            (SELECT COUNT(*) FROM change_polygons WHERE analysis_run_id = r.id) as change_polygon_count
        FROM analysis_runs r
        JOIN aois a ON r.aoi_id = a.id
        ORDER BY r.created_at DESC
        LIMIT :limit;
        """
    )
    result = await db.execute(query, {"limit": limit})
    rows = result.fetchall()

    items = []
    for row in rows:
        items.append(
            {
                "id": str(row.id),
                "aoi_id": str(row.aoi_id),
                "aoi_name": row.aoi_name,
                "analysis_type": row.analysis_type,
                "threshold": float(row.threshold),
                "ndvi_change": float(row.ndvi_change) if row.ndvi_change is not None else None,
                "total_change_area_m2": float(row.total_change_area_m2) if row.total_change_area_m2 is not None else 0.0,
                "total_change_area_ha": float(row.total_change_area_ha) if row.total_change_area_ha is not None else 0.0,
                "change_polygon_count": int(row.change_polygon_count),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"count": len(items), "analysis_runs": items}


@router.get("/{analysis_id}/nearby-infrastructure")
async def get_nearby_infrastructure(
    analysis_id: uuid.UUID,
    radius_m: float = Query(1000.0, gt=0, le=100000.0, description="Search proximity radius in meters (default: 1000.0 m)"),
    format: Optional[str] = Query("json", description="Response format: 'json' or 'geojson'"),
    db: AsyncSession = Depends(get_async_db),
):
    """Query PostGIS for infrastructure within `radius_m` of detected vegetation-change polygons.

    Uses real PostGIS ST_DWithin and ST_Distance calculations on WGS84 geography.
    Returns results sorted by actual geodesic distance.
    """
    try:
        analysis_proximity = await analyze_infrastructure_proximity(
            db=db,
            analysis_id=analysis_id,
            radius_m=radius_m,
        )

        if format == "geojson":
            features = []
            for item in analysis_proximity["infrastructure"]:
                geom = item.get("geometry")
                props = {k: v for k, v in item.items() if k != "geometry"}
                features.append(
                    {
                        "type": "Feature",
                        "id": item["id"],
                        "geometry": geom,
                        "properties": props,
                    }
                )

            return {
                "type": "FeatureCollection",
                "analysis_id": str(analysis_id),
                "radius_m": radius_m,
                "count": len(features),
                "associated_change_area_m2": analysis_proximity["associated_change_area_m2"],
                "associated_change_area_ha": analysis_proximity["associated_change_area_ha"],
                "features": features,
            }

        return analysis_proximity
    except GISValidationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spatial Query Error: {str(e)}")


@router.get("/{analysis_id}/spatial-summary")
async def get_spatial_summary(
    analysis_id: uuid.UUID,
    radius_m: float = Query(1000.0, gt=0, le=100000.0, description="Proximity radius in meters (default: 1000.0 m)"),
    db: AsyncSession = Depends(get_async_db),
):
    """Retrieve comprehensive PostGIS spatial summary for an analysis run.

    Includes:
    - Change area metrics & aggregations (total area, min/max/mean polygon area)
    - AOI containment validation (verifying polygons lie within AOI)
    - Infrastructure proximity metrics (closest asset, asset type breakdown)
    - Population zone context (intersecting/nearby population)
    """
    try:
        summary = await get_analysis_spatial_summary(
            db=db,
            analysis_id=analysis_id,
            radius_m=radius_m,
        )
        return summary
    except GISValidationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spatial Summary Error: {str(e)}")


@router.get("/{analysis_id}/population-context")
async def get_population_context(
    analysis_id: uuid.UUID,
    radius_m: float = Query(1000.0, gt=0, le=100000.0, description="Search proximity radius in meters (default: 1000.0 m)"),
    format: Optional[str] = Query("json", description="Response format: 'json' or 'geojson'"),
    db: AsyncSession = Depends(get_async_db),
):
    """Query PostGIS for population zones intersecting or within `radius_m` of change polygons."""
    try:
        pop_context = await analyze_population_proximity(
            db=db,
            analysis_id=analysis_id,
            radius_m=radius_m,
        )

        if format == "geojson":
            features = []
            for zone in pop_context["zones"]:
                geom = zone.get("geometry")
                props = {k: v for k, v in zone.items() if k != "geometry"}
                features.append(
                    {
                        "type": "Feature",
                        "id": zone["id"],
                        "geometry": geom,
                        "properties": props,
                    }
                )

            return {
                "type": "FeatureCollection",
                "analysis_id": str(analysis_id),
                "radius_m": radius_m,
                "count": len(features),
                "intersecting_zones_count": pop_context["intersecting_zones_count"],
                "total_intersecting_population": pop_context["total_intersecting_population"],
                "features": features,
            }

        return pop_context
    except GISValidationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Population Context Error: {str(e)}")


@router.get("/{analysis_id}/spatial-intersection")
async def get_spatial_intersection(
    analysis_id: uuid.UUID,
    layer: str = Query("infrastructure", description="Target layer: 'infrastructure', 'population_zones', or 'aoi'"),
    db: AsyncSession = Depends(get_async_db),
):
    """Compute exact PostGIS ST_Intersects and ST_Intersection between change polygons and layer."""
    try:
        result = await run_spatial_intersection(
            db=db,
            analysis_id=analysis_id,
            layer=layer,
        )
        return result
    except GISValidationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spatial Intersection Error: {str(e)}")


@router.get("/{analysis_id}/aoi-containment")
async def get_aoi_containment(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Validate whether all change polygons for the analysis run are topologically contained within AOI."""
    try:
        result = await validate_aoi_containment(
            db=db,
            analysis_id=analysis_id,
        )
        return result
    except GISValidationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AOI Containment Error: {str(e)}")

