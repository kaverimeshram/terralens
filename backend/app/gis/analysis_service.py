"""TerraLens Deterministic Analysis Orchestrator Service.

Coordinates the end-to-end GIS pipeline:
1. Scene & AOI validation
2. Multispectral raster band compatibility verification
3. NDVI computation (Before & After)
4. Temporal NDVI difference calculation
5. Significant vegetation change thresholding
6. Raster-to-vector polygonization
7. Geodesic metric area calculation (m² and ha)
8. PostGIS persistence for analysis runs and change polygons
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import MultiPolygon, Polygon, mapping

from app.gis.ndvi import (
    calculate_ndvi_from_files,
    calculate_ndvi_difference,
    detect_significant_change,
    write_geotiff,
)
from app.gis.vectorization import polygonize_change_raster
from app.gis.validation import (
    GISValidationError,
    validate_raster_compatibility,
    validate_ndvi_array,
)

logger = logging.getLogger("terralens.gis.analysis")


def resolve_raster_path(path_str: Union[str, Path]) -> Path:
    """Resolve raster path whether given as absolute or relative to workspace/backend root."""
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return p

    # Check relative to cwd
    if p.exists():
        return p.resolve()

    # Search common root anchor locations
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    candidate_1 = project_root / p
    if candidate_1.exists():
        return candidate_1.resolve()

    backend_root = project_root / "backend"
    candidate_2 = backend_root / p
    if candidate_2.exists():
        return candidate_2.resolve()

    # If path starts with "backend/", strip it when searching inside backend_root
    if str(p).startswith("backend/"):
        stripped = Path(str(p)[len("backend/"):])
        candidate_3 = backend_root / stripped
        if candidate_3.exists():
            return candidate_3.resolve()

    raise FileNotFoundError(f"Could not resolve raster path on disk: '{path_str}'")


async def run_ndvi_change_analysis(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    before_scene_id: uuid.UUID,
    after_scene_id: uuid.UUID,
    threshold: float = -0.20,
    minimum_area_m2: float = 500.0,
    output_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Execute complete deterministic NDVI change detection pipeline and persist to PostGIS."""
    # 1. Fetch AOI and Scene records from PostGIS
    aoi_query = text("SELECT id, name, description, bounding_box FROM aois WHERE id = :id;")
    aoi_res = await db.execute(aoi_query, {"id": aoi_id})
    aoi_row = aoi_res.fetchone()
    if not aoi_row:
        raise GISValidationError(f"AOI with ID '{aoi_id}' not found")

    scenes_query = text(
        """
        SELECT id, aoi_id, scene_identifier, satellite, sensor, acquisition_date, 
               cloud_cover, spatial_resolution, raster_path, red_band_path, nir_band_path, metadata
        FROM satellite_scenes
        WHERE id IN (:before_id, :after_id);
        """
    )
    scenes_res = await db.execute(
        scenes_query, {"before_id": before_scene_id, "after_id": after_scene_id}
    )
    scenes_rows = {str(r.id): r for r in scenes_res.fetchall()}

    before_row = scenes_rows.get(str(before_scene_id))
    after_row = scenes_rows.get(str(after_scene_id))

    if not before_row:
        raise GISValidationError(f"Before satellite scene with ID '{before_scene_id}' not found")
    if not after_row:
        raise GISValidationError(f"After satellite scene with ID '{after_scene_id}' not found")

    # Validate AOI ownership
    if before_row.aoi_id != aoi_id:
        raise GISValidationError(
            f"Before scene '{before_row.scene_identifier}' does not belong to AOI '{aoi_row.name}'"
        )
    if after_row.aoi_id != aoi_id:
        raise GISValidationError(
            f"After scene '{after_row.scene_identifier}' does not belong to AOI '{aoi_row.name}'"
        )

    # Validate band paths exist
    if not before_row.red_band_path or not before_row.nir_band_path:
        raise GISValidationError(
            f"Before scene '{before_row.scene_identifier}' is missing Red or NIR band paths"
        )
    if not after_row.red_band_path or not after_row.nir_band_path:
        raise GISValidationError(
            f"After scene '{after_row.scene_identifier}' is missing Red or NIR band paths"
        )

    # Resolve disk paths
    before_red_path = resolve_raster_path(before_row.red_band_path)
    before_nir_path = resolve_raster_path(before_row.nir_band_path)
    after_red_path = resolve_raster_path(after_row.red_band_path)
    after_nir_path = resolve_raster_path(after_row.nir_band_path)

    # Validate raster grid alignment
    validate_raster_compatibility(before_red_path, before_nir_path)
    validate_raster_compatibility(after_red_path, after_nir_path)
    validate_raster_compatibility(before_red_path, after_red_path)

    # Setup outputs directory
    if output_dir:
        out_dir = Path(output_dir)
    else:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        out_dir = project_root / "backend" / "data" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    before_ndvi_file = out_dir / "before_ndvi.tif"
    after_ndvi_file = out_dir / "after_ndvi.tif"
    diff_ndvi_file = out_dir / "ndvi_difference.tif"
    sig_change_file = out_dir / "significant_change.tif"

    # 2. Compute Before NDVI
    before_ndvi, profile = calculate_ndvi_from_files(
        before_red_path, before_nir_path, output_path=before_ndvi_file
    )
    validate_ndvi_array(before_ndvi)

    # 3. Compute After NDVI
    after_ndvi, _ = calculate_ndvi_from_files(
        after_red_path, after_nir_path, output_path=after_ndvi_file
    )
    validate_ndvi_array(after_ndvi)

    # 4. Compute NDVI Difference (after - before)
    diff_ndvi = calculate_ndvi_difference(before_ndvi, after_ndvi)
    write_geotiff(diff_ndvi_file, diff_ndvi, profile)

    # 5. Detect Significant Change Mask
    change_mask = detect_significant_change(diff_ndvi, threshold=threshold)
    write_geotiff(sig_change_file, change_mask.astype(np.float32), profile, nodata=-9999.0)

    # 6. Vectorize significant change into GIS Polygons
    crs_str = str(profile.get("crs", "EPSG:4326"))
    transform = profile["transform"]
    change_features = polygonize_change_raster(
        change_mask=change_mask,
        ndvi_difference=diff_ndvi,
        before_ndvi=before_ndvi,
        after_ndvi=after_ndvi,
        transform=transform,
        crs_str=crs_str,
        min_area_m2=minimum_area_m2,
        target_value=-1,  # Significant decrease
        change_type_label="detected vegetation decrease",
    )

    # 7. Compute Summary Statistics
    valid_before = before_ndvi[before_ndvi != -9999.0]
    valid_after = after_ndvi[after_ndvi != -9999.0]
    valid_diff = diff_ndvi[diff_ndvi != -9999.0]

    mean_before_val = float(np.mean(valid_before)) if len(valid_before) > 0 else 0.0
    mean_after_val = float(np.mean(valid_after)) if len(valid_after) > 0 else 0.0
    mean_diff_val = float(np.mean(valid_diff)) if len(valid_diff) > 0 else 0.0
    changed_pixels_count = int(np.sum(change_mask == -1))

    total_change_area_m2 = round(
        sum(f["properties"]["area_m2"] for f in change_features), 2
    )
    total_change_area_ha = round(total_change_area_m2 / 10000.0, 4)

    # 8. Store AnalysisRun in PostGIS
    analysis_id = uuid.uuid4()
    now_utc = datetime.now(timezone.utc)
    activity_log = [
        {"step": "validate_scenes", "status": "COMPLETED", "timestamp": now_utc.isoformat()},
        {"step": "calculate_before_ndvi", "status": "COMPLETED", "timestamp": now_utc.isoformat()},
        {"step": "calculate_after_ndvi", "status": "COMPLETED", "timestamp": now_utc.isoformat()},
        {"step": "calculate_ndvi_difference", "status": "COMPLETED", "timestamp": now_utc.isoformat()},
        {"step": "threshold_significant_change", "status": "COMPLETED", "threshold": threshold, "timestamp": now_utc.isoformat()},
        {"step": "polygonize_vectors", "status": "COMPLETED", "polygon_count": len(change_features), "timestamp": now_utc.isoformat()},
        {"step": "geodesic_area_calculation", "status": "COMPLETED", "total_area_ha": total_change_area_ha, "timestamp": now_utc.isoformat()},
    ]

    validation_report = {
        "status": "PASSED",
        "provenance": "Synthetic Sentinel-2-like remote-sensing simulation data for development and testing.",
        "crs": crs_str,
        "grid_dimensions": f"{profile['width']}x{profile['height']}",
        "cloud_cover_before": float(before_row.cloud_cover),
        "cloud_cover_after": float(after_row.cloud_cover),
        "valid_ndvi_range": [-1.0, 1.0],
        "changed_pixels_count": changed_pixels_count,
        "total_pixels_count": int(profile["width"] * profile["height"]),
    }

    insert_run_query = text(
        """
        INSERT INTO analysis_runs (
            id, aoi_id, before_scene_id, after_scene_id, analysis_type, 
            threshold, ndvi_change, total_change_area_m2, status, 
            validation_report, activity_log, created_at
        ) VALUES (
            :id, :aoi_id, :before_id, :after_id, :analysis_type, 
            :threshold, :ndvi_change, :total_area_m2, :status, 
            :val_rep, :act_log, :created_at
        );
        """
    )
    await db.execute(
        insert_run_query,
        {
            "id": analysis_id,
            "aoi_id": aoi_id,
            "before_id": before_scene_id,
            "after_id": after_scene_id,
            "analysis_type": "NDVI_CHANGE",
            "threshold": threshold,
            "ndvi_change": round(mean_diff_val, 3),
            "total_area_m2": total_change_area_m2,
            "status": "COMPLETED",
            "val_rep": json.dumps(validation_report),
            "act_log": json.dumps(activity_log),
            "created_at": now_utc,
        },
    )

    # 9. Store ChangePolygons in PostGIS
    insert_poly_query = text(
        """
        INSERT INTO change_polygons (
            id, analysis_run_id, geometry, area_m2, change_value, 
            mean_before_ndvi, mean_after_ndvi, created_at
        ) VALUES (
            :id, :analysis_run_id, 
            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_geojson), 4326)), 
            :area_m2, :change_value, :mean_before, :mean_after, :created_at
        );
        """
    )

    for feat in change_features:
        poly_id = uuid.uuid4()
        props = feat["properties"]
        geom_json = json.dumps(feat["geometry"])
        await db.execute(
            insert_poly_query,
            {
                "id": poly_id,
                "analysis_run_id": analysis_id,
                "geom_geojson": geom_json,
                "area_m2": props["area_m2"],
                "change_value": props["mean_ndvi_change"],
                "mean_before": props["mean_before_ndvi"],
                "mean_after": props["mean_after_ndvi"],
                "created_at": now_utc,
            },
        )

    await db.commit()

    return {
        "analysis_id": str(analysis_id),
        "status": "COMPLETED",
        "aoi": {
            "id": str(aoi_row.id),
            "name": aoi_row.name,
            "description": aoi_row.description,
        },
        "before_scene": {
            "id": str(before_row.id),
            "scene_identifier": before_row.scene_identifier,
            "acquisition_date": before_row.acquisition_date.isoformat(),
            "cloud_cover": float(before_row.cloud_cover),
        },
        "after_scene": {
            "id": str(after_row.id),
            "scene_identifier": after_row.scene_identifier,
            "acquisition_date": after_row.acquisition_date.isoformat(),
            "cloud_cover": float(after_row.cloud_cover),
        },
        "metrics": {
            "mean_before_ndvi": round(mean_before_val, 4),
            "mean_after_ndvi": round(mean_after_val, 4),
            "mean_ndvi_difference": round(mean_diff_val, 4),
            "threshold": threshold,
            "minimum_area_m2": minimum_area_m2,
            "changed_pixels_count": changed_pixels_count,
            "change_polygon_count": len(change_features),
            "total_change_area_m2": total_change_area_m2,
            "total_change_area_ha": total_change_area_ha,
        },
        "raster_outputs": {
            "before_ndvi": str(before_ndvi_file),
            "after_ndvi": str(after_ndvi_file),
            "ndvi_difference": str(diff_ndvi_file),
            "significant_change": str(sig_change_file),
        },
        "validation_report": validation_report,
        "activity_log": activity_log,
    }
