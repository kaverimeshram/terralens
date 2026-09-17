"""TerraLens PostGIS Spatial Intelligence Engine Service.

Provides deterministic, database-native PostGIS spatial queries:
1. find_nearby_infrastructure: Proximity search using ST_DWithin & ST_Distance on geography.
2. run_spatial_intersection: Exact geometric intersection with ST_Intersects & ST_Intersection.
3. analyze_infrastructure_proximity: Higher-level factual proximity analysis.
4. analyze_population_proximity: Demographic context and population zone intersection analysis.
5. get_change_area_summary: Spatial aggregation of detected change polygons.
6. validate_aoi_containment: PostGIS topological containment validation against AOI boundaries.
7. get_analysis_spatial_summary: Unified spatial report combining all PostGIS queries.

All distance calculations and spatial predicates are evaluated directly by PostGIS
on the WGS84 spheroid (EPSG:4326 / geography).
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gis.validation import GISValidationError

logger = logging.getLogger("terralens.gis.spatial")


async def get_change_area_summary(
    db: AsyncSession,
    analysis_id: uuid.UUID,
) -> Dict[str, Any]:
    """Calculate spatial aggregations on detected change polygons using PostGIS.

    Computes:
    - total_change_area_m2 & total_change_area_ha
    - change_polygon_count
    - min_area_m2, max_area_m2, mean_area_m2
    - mean_ndvi_change
    """
    # Verify analysis run exists
    check_query = text("SELECT id, status, aoi_id FROM analysis_runs WHERE id = :id;")
    check_res = await db.execute(check_query, {"id": analysis_id})
    analysis_row = check_res.fetchone()
    if not analysis_row:
        raise GISValidationError(f"Analysis run '{analysis_id}' not found")

    agg_query = text(
        """
        SELECT 
            COUNT(id) as polygon_count,
            COALESCE(SUM(area_m2), 0.0) as total_area_m2,
            COALESCE(MIN(area_m2), 0.0) as min_area_m2,
            COALESCE(MAX(area_m2), 0.0) as max_area_m2,
            COALESCE(AVG(area_m2), 0.0) as mean_area_m2,
            COALESCE(AVG(change_value), 0.0) as avg_ndvi_change
        FROM change_polygons
        WHERE analysis_run_id = :analysis_id;
        """
    )
    result = await db.execute(agg_query, {"analysis_id": analysis_id})
    row = result.fetchone()

    total_m2 = round(float(row.total_area_m2), 2)
    total_ha = round(total_m2 / 10000.0, 4)

    return {
        "analysis_id": str(analysis_id),
        "change_polygon_count": int(row.polygon_count),
        "total_change_area_m2": total_m2,
        "total_change_area_ha": total_ha,
        "min_polygon_area_m2": round(float(row.min_area_m2), 2),
        "max_polygon_area_m2": round(float(row.max_area_m2), 2),
        "mean_polygon_area_m2": round(float(row.mean_area_m2), 2),
        "mean_ndvi_change": round(float(row.avg_ndvi_change), 4),
    }


async def validate_aoi_containment(
    db: AsyncSession,
    analysis_id: uuid.UUID,
) -> Dict[str, Any]:
    """Verify that all generated change polygons lie within the analysis AOI boundary.

    Uses PostGIS spatial predicates:
    - ST_Within(cp.geometry, a.geometry)
    - ST_Intersects(cp.geometry, a.geometry)
    - ST_Area(ST_Intersection(cp.geometry, a.geometry)::geography) / ST_Area(cp.geometry::geography)
    """
    check_query = text("SELECT id, aoi_id FROM analysis_runs WHERE id = :id;")
    check_res = await db.execute(check_query, {"id": analysis_id})
    analysis_row = check_res.fetchone()
    if not analysis_row:
        raise GISValidationError(f"Analysis run '{analysis_id}' not found")

    containment_query = text(
        """
        SELECT 
            cp.id as polygon_id,
            cp.area_m2,
            ST_Within(cp.geometry, a.geometry) as is_strictly_within,
            ST_Intersects(cp.geometry, a.geometry) as intersects_aoi,
            CASE 
                WHEN ST_Area(cp.geometry::geography) > 0 
                THEN ST_Area(ST_Intersection(cp.geometry, a.geometry)::geography) / ST_Area(cp.geometry::geography)
                ELSE 1.0 
            END as containment_ratio
        FROM change_polygons cp
        JOIN analysis_runs r ON cp.analysis_run_id = r.id
        JOIN aois a ON r.aoi_id = a.id
        WHERE cp.analysis_run_id = :analysis_id
        ORDER BY cp.area_m2 DESC;
        """
    )
    result = await db.execute(containment_query, {"analysis_id": analysis_id})
    rows = result.fetchall()

    if not rows:
        return {
            "analysis_id": str(analysis_id),
            "aoi_id": str(analysis_row.aoi_id),
            "total_polygons": 0,
            "contained_polygons_count": 0,
            "outside_polygons_count": 0,
            "containment_ratio": 1.0,
            "all_polygons_contained": True,
            "details": [],
        }

    contained_count = sum(1 for r in rows if r.is_strictly_within or r.containment_ratio >= 0.999)
    outside_count = len(rows) - contained_count
    overall_ratio = sum(float(r.containment_ratio) for r in rows) / len(rows)

    details = [
        {
            "polygon_id": str(r.polygon_id),
            "area_m2": round(float(r.area_m2), 2),
            "is_strictly_within": bool(r.is_strictly_within),
            "intersects_aoi": bool(r.intersects_aoi),
            "containment_ratio": round(float(r.containment_ratio), 4),
        }
        for r in rows
    ]

    return {
        "analysis_id": str(analysis_id),
        "aoi_id": str(analysis_row.aoi_id),
        "total_polygons": len(rows),
        "contained_polygons_count": contained_count,
        "outside_polygons_count": outside_count,
        "containment_ratio": round(overall_ratio, 4),
        "all_polygons_contained": outside_count == 0,
        "details": details,
    }


async def find_nearby_infrastructure(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    radius_m: float = 1000.0,
) -> List[Dict[str, Any]]:
    """Query PostGIS for infrastructure within radius_m of any detected change polygon.

    Uses PostGIS spatial index with:
    - ST_DWithin(i.geometry::geography, cp.geometry::geography, :radius_m)
    - ST_Distance(i.geometry::geography, cp.geometry::geography)

    Returns distinct closest infrastructure items, ordered by actual distance in meters.
    """
    if radius_m <= 0:
        raise GISValidationError("Search radius must be greater than 0 meters")

    check_query = text("SELECT id FROM analysis_runs WHERE id = :id;")
    check_res = await db.execute(check_query, {"id": analysis_id})
    if not check_res.fetchone():
        raise GISValidationError(f"Analysis run '{analysis_id}' not found")

    query = text(
        """
        WITH ranked_matches AS (
            SELECT 
                i.id as infrastructure_id,
                i.aoi_id,
                i.name,
                i.type,
                i.metadata,
                ST_AsGeoJSON(i.geometry) as geojson_geom,
                cp.id as nearest_change_polygon_id,
                cp.area_m2 as change_polygon_area_m2,
                cp.change_value as change_polygon_mean_ndvi_change,
                ST_Distance(i.geometry::geography, cp.geometry::geography) as distance_m,
                ROW_NUMBER() OVER (
                    PARTITION BY i.id 
                    ORDER BY ST_Distance(i.geometry::geography, cp.geometry::geography) ASC
                ) as rank_num
            FROM infrastructure i
            JOIN change_polygons cp ON cp.analysis_run_id = :analysis_id
            WHERE ST_DWithin(i.geometry::geography, cp.geometry::geography, :radius_m)
        )
        SELECT 
            infrastructure_id,
            aoi_id,
            name,
            type,
            metadata,
            geojson_geom,
            nearest_change_polygon_id,
            change_polygon_area_m2,
            change_polygon_mean_ndvi_change,
            distance_m
        FROM ranked_matches
        WHERE rank_num = 1
        ORDER BY distance_m ASC, name ASC;
        """
    )
    result = await db.execute(query, {"analysis_id": analysis_id, "radius_m": radius_m})
    rows = result.fetchall()

    items = []
    for r in rows:
        geom = json.loads(r.geojson_geom) if r.geojson_geom else None
        items.append(
            {
                "id": str(r.infrastructure_id),
                "aoi_id": str(r.aoi_id) if r.aoi_id else None,
                "name": r.name,
                "type": r.type,
                "distance_m": round(float(r.distance_m), 1),
                "nearest_change_polygon_id": str(r.nearest_change_polygon_id),
                "change_polygon_area_m2": round(float(r.change_polygon_area_m2), 2),
                "change_polygon_mean_ndvi_change": round(float(r.change_polygon_mean_ndvi_change), 4),
                "geometry": geom,
                "metadata": r.metadata or {},
            }
        )

    return items


async def analyze_infrastructure_proximity(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    radius_m: float = 1000.0,
) -> Dict[str, Any]:
    """Perform comprehensive, factual infrastructure proximity analysis.

    Returns:
    - infrastructure_count
    - infrastructure list with distances & nearest polygon IDs
    - breakdown by asset type
    - closest infrastructure item
    - total vegetation change area associated with nearby change polygons
    - strictly factual descriptive summary without causal claims
    """
    items = await find_nearby_infrastructure(db=db, analysis_id=analysis_id, radius_m=radius_m)

    # Compute associated change area for polygons that are within radius of at least one asset
    associated_poly_query = text(
        """
        SELECT 
            COUNT(DISTINCT cp.id) as nearby_polygon_count,
            COALESCE(SUM(cp.area_m2), 0.0) as total_associated_area_m2
        FROM change_polygons cp
        JOIN infrastructure i ON ST_DWithin(cp.geometry::geography, i.geometry::geography, :radius_m)
        WHERE cp.analysis_run_id = :analysis_id;
        """
    )
    assoc_res = await db.execute(associated_poly_query, {"analysis_id": analysis_id, "radius_m": radius_m})
    assoc_row = assoc_res.fetchone()

    total_assoc_m2 = round(float(assoc_row.total_associated_area_m2), 2)
    total_assoc_ha = round(total_assoc_m2 / 10000.0, 4)

    # Breakdown by type
    by_type: Dict[str, int] = {}
    for item in items:
        t = item["type"]
        by_type[t] = by_type.get(t, 0) + 1

    closest_item = items[0] if items else None

    # Construct factual summary statements (NO causal claims)
    factual_statements: List[str] = []
    if not items:
        factual_statements.append(
            f"No infrastructure assets found within {radius_m:.0f} m of detected vegetation-change polygons."
        )
    else:
        factual_statements.append(
            f"{len(items)} infrastructure asset(s) located within {radius_m:.0f} m of detected vegetation-change polygons."
        )
        if closest_item:
            dist = closest_item["distance_m"]
            if dist == 0.0:
                factual_statements.append(
                    f"'{closest_item['name']}' ({closest_item['type']}) directly intersects a detected vegetation-change polygon."
                )
            else:
                factual_statements.append(
                    f"Closest infrastructure asset is '{closest_item['name']}' ({closest_item['type']}) at a distance of {dist:.1f} m."
                )

    return {
        "analysis_id": str(analysis_id),
        "radius_m": radius_m,
        "infrastructure_count": len(items),
        "infrastructure_by_type": by_type,
        "closest_infrastructure": closest_item,
        "associated_change_polygon_count": int(assoc_row.nearby_polygon_count),
        "associated_change_area_m2": total_assoc_m2,
        "associated_change_area_ha": total_assoc_ha,
        "infrastructure": items,
        "factual_summary": factual_statements,
    }


async def analyze_population_proximity(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    radius_m: float = 1000.0,
) -> Dict[str, Any]:
    """Query PostGIS for population zones intersecting or within radius_m of change polygons.

    Uses:
    - ST_DWithin(pz.geometry::geography, cp.geometry::geography, :radius_m)
    - ST_Intersects(pz.geometry, cp.geometry)
    - ST_Distance(pz.geometry::geography, cp.geometry::geography)
    - ST_Area(ST_Intersection(pz.geometry, cp.geometry)::geography) / 10000.0
    """
    if radius_m <= 0:
        raise GISValidationError("Search radius must be greater than 0 meters")

    check_query = text("SELECT id FROM analysis_runs WHERE id = :id;")
    check_res = await db.execute(check_query, {"id": analysis_id})
    if not check_res.fetchone():
        raise GISValidationError(f"Analysis run '{analysis_id}' not found")

    query = text(
        """
        WITH ranked_zones AS (
            SELECT 
                pz.id as zone_id,
                pz.aoi_id,
                pz.name,
                pz.population,
                pz.metadata,
                ST_AsGeoJSON(pz.geometry) as geojson_geom,
                ST_Intersects(pz.geometry, cp.geometry) as intersects_change,
                ST_Distance(pz.geometry::geography, cp.geometry::geography) as distance_m,
                ST_Area(pz.geometry::geography) / 10000.0 as zone_area_ha,
                CASE 
                    WHEN ST_Intersects(pz.geometry, cp.geometry) 
                    THEN ST_Area(ST_Intersection(pz.geometry, cp.geometry)::geography) / 10000.0
                    ELSE 0.0
                END as intersection_area_ha,
                cp.id as nearest_change_polygon_id,
                ROW_NUMBER() OVER (
                    PARTITION BY pz.id 
                    ORDER BY ST_Distance(pz.geometry::geography, cp.geometry::geography) ASC
                ) as rank_num
            FROM population_zones pz
            JOIN change_polygons cp ON cp.analysis_run_id = :analysis_id
            WHERE ST_DWithin(pz.geometry::geography, cp.geometry::geography, :radius_m)
        )
        SELECT 
            zone_id,
            aoi_id,
            name,
            population,
            metadata,
            geojson_geom,
            intersects_change,
            distance_m,
            zone_area_ha,
            intersection_area_ha,
            nearest_change_polygon_id
        FROM ranked_zones
        WHERE rank_num = 1
        ORDER BY distance_m ASC, name ASC;
        """
    )
    result = await db.execute(query, {"analysis_id": analysis_id, "radius_m": radius_m})
    rows = result.fetchall()

    zones = []
    intersecting_count = 0
    total_intersecting_pop = 0

    for r in rows:
        geom = json.loads(r.geojson_geom) if r.geojson_geom else None
        intersects = bool(r.intersects_change)
        if intersects:
            intersecting_count += 1
            total_intersecting_pop += int(r.population)

        zones.append(
            {
                "id": str(r.zone_id),
                "aoi_id": str(r.aoi_id) if r.aoi_id else None,
                "name": r.name,
                "population": int(r.population),
                "distance_m": round(float(r.distance_m), 1),
                "intersects_change": intersects,
                "zone_area_ha": round(float(r.zone_area_ha), 2),
                "intersection_area_ha": round(float(r.intersection_area_ha), 4),
                "nearest_change_polygon_id": str(r.nearest_change_polygon_id),
                "geometry": geom,
                "metadata": r.metadata or {},
            }
        )

    factual_statements: List[str] = []
    if not zones:
        factual_statements.append(
            f"No population zones located within {radius_m:.0f} m of detected vegetation-change polygons."
        )
    else:
        factual_statements.append(
            f"{len(zones)} population zone(s) identified within {radius_m:.0f} m."
        )
        if intersecting_count > 0:
            factual_statements.append(
                f"{intersecting_count} zone(s) (total registered population: {total_intersecting_pop:,}) directly intersect detected vegetation-change areas."
            )

    return {
        "analysis_id": str(analysis_id),
        "radius_m": radius_m,
        "population_zones_count": len(zones),
        "intersecting_zones_count": intersecting_count,
        "total_intersecting_population": total_intersecting_pop,
        "zones": zones,
        "factual_summary": factual_statements,
    }


async def run_spatial_intersection(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    layer: str = "infrastructure",
) -> Dict[str, Any]:
    """Compute exact spatial intersections between detected change polygons and a target layer.

    Supported layers:
    - 'infrastructure': Intersects change polygons with infrastructure features
    - 'population_zones': Intersects change polygons with population zones
    - 'aoi': Intersects change polygons with AOI boundaries
    """
    layer_clean = layer.lower().strip()
    if layer_clean not in ("infrastructure", "population_zones", "aoi"):
        raise GISValidationError(
            f"Unsupported layer '{layer}'. Must be one of: 'infrastructure', 'population_zones', 'aoi'"
        )

    check_query = text("SELECT id, aoi_id FROM analysis_runs WHERE id = :id;")
    check_res = await db.execute(check_query, {"id": analysis_id})
    analysis_row = check_res.fetchone()
    if not analysis_row:
        raise GISValidationError(f"Analysis run '{analysis_id}' not found")

    if layer_clean == "infrastructure":
        query = text(
            """
            SELECT 
                cp.id as change_polygon_id,
                cp.area_m2 as change_polygon_area_m2,
                i.id as feature_id,
                i.name as feature_name,
                i.type as feature_type,
                ST_AsGeoJSON(ST_Intersection(cp.geometry, i.geometry)) as intersection_geojson,
                ST_Distance(cp.geometry::geography, i.geometry::geography) as distance_m
            FROM change_polygons cp
            JOIN infrastructure i ON ST_Intersects(cp.geometry, i.geometry)
            WHERE cp.analysis_run_id = :analysis_id
            ORDER BY cp.area_m2 DESC;
            """
        )
        res = await db.execute(query, {"analysis_id": analysis_id})
        rows = res.fetchall()

        intersections = []
        for r in rows:
            intersections.append(
                {
                    "change_polygon_id": str(r.change_polygon_id),
                    "change_polygon_area_m2": round(float(r.change_polygon_area_m2), 2),
                    "feature_id": str(r.feature_id),
                    "feature_name": r.feature_name,
                    "feature_type": r.feature_type,
                    "distance_m": round(float(r.distance_m), 1),
                    "intersection_geometry": json.loads(r.intersection_geojson) if r.intersection_geojson else None,
                }
            )

        return {
            "analysis_id": str(analysis_id),
            "layer": layer_clean,
            "intersection_count": len(intersections),
            "intersections": intersections,
        }

    elif layer_clean == "population_zones":
        query = text(
            """
            SELECT 
                cp.id as change_polygon_id,
                cp.area_m2 as change_polygon_area_m2,
                pz.id as feature_id,
                pz.name as feature_name,
                pz.population as population,
                ST_Area(ST_Intersection(cp.geometry, pz.geometry)::geography) as intersection_area_m2,
                (ST_Area(ST_Intersection(cp.geometry, pz.geometry)::geography) / 10000.0) as intersection_area_ha,
                ST_AsGeoJSON(ST_Intersection(cp.geometry, pz.geometry)) as intersection_geojson,
                ST_Distance(cp.geometry::geography, pz.geometry::geography) as distance_m
            FROM change_polygons cp
            JOIN population_zones pz ON ST_Intersects(cp.geometry, pz.geometry)
            WHERE cp.analysis_run_id = :analysis_id
            ORDER BY intersection_area_m2 DESC;
            """
        )
        res = await db.execute(query, {"analysis_id": analysis_id})
        rows = res.fetchall()

        intersections = []
        for r in rows:
            intersections.append(
                {
                    "change_polygon_id": str(r.change_polygon_id),
                    "change_polygon_area_m2": round(float(r.change_polygon_area_m2), 2),
                    "feature_id": str(r.feature_id),
                    "feature_name": r.feature_name,
                    "population": int(r.population),
                    "intersection_area_m2": round(float(r.intersection_area_m2), 2),
                    "intersection_area_ha": round(float(r.intersection_area_ha), 4),
                    "distance_m": round(float(r.distance_m), 1),
                    "intersection_geometry": json.loads(r.intersection_geojson) if r.intersection_geojson else None,
                }
            )

        return {
            "analysis_id": str(analysis_id),
            "layer": layer_clean,
            "intersection_count": len(intersections),
            "intersections": intersections,
        }

    else:  # 'aoi'
        query = text(
            """
            SELECT 
                cp.id as change_polygon_id,
                cp.area_m2 as change_polygon_area_m2,
                a.id as feature_id,
                a.name as feature_name,
                ST_Within(cp.geometry, a.geometry) as is_strictly_within,
                ST_Area(ST_Intersection(cp.geometry, a.geometry)::geography) as intersection_area_m2,
                ST_AsGeoJSON(ST_Intersection(cp.geometry, a.geometry)) as intersection_geojson
            FROM change_polygons cp
            JOIN analysis_runs r ON cp.analysis_run_id = r.id
            JOIN aois a ON r.aoi_id = a.id
            WHERE cp.analysis_run_id = :analysis_id
            ORDER BY cp.area_m2 DESC;
            """
        )
        res = await db.execute(query, {"analysis_id": analysis_id})
        rows = res.fetchall()

        intersections = []
        for r in rows:
            intersections.append(
                {
                    "change_polygon_id": str(r.change_polygon_id),
                    "change_polygon_area_m2": round(float(r.change_polygon_area_m2), 2),
                    "feature_id": str(r.feature_id),
                    "feature_name": r.feature_name,
                    "is_strictly_within": bool(r.is_strictly_within),
                    "intersection_area_m2": round(float(r.intersection_area_m2), 2),
                    "intersection_geometry": json.loads(r.intersection_geojson) if r.intersection_geojson else None,
                }
            )

        return {
            "analysis_id": str(analysis_id),
            "layer": layer_clean,
            "intersection_count": len(intersections),
            "intersections": intersections,
        }


async def get_analysis_spatial_summary(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    radius_m: float = 1000.0,
) -> Dict[str, Any]:
    """Generate a unified PostGIS spatial summary for an analysis run.

    Combines:
    - Change area metrics & aggregations
    - AOI containment validation
    - Infrastructure proximity metrics
    - Population zone context
    """
    area_summary = await get_change_area_summary(db=db, analysis_id=analysis_id)
    containment = await validate_aoi_containment(db=db, analysis_id=analysis_id)
    infra_proximity = await analyze_infrastructure_proximity(db=db, analysis_id=analysis_id, radius_m=radius_m)
    pop_proximity = await analyze_population_proximity(db=db, analysis_id=analysis_id, radius_m=radius_m)

    return {
        "analysis_id": str(analysis_id),
        "radius_m": radius_m,
        "change_metrics": area_summary,
        "aoi_containment": {
            "all_contained": containment["all_polygons_contained"],
            "total_polygons": containment["total_polygons"],
            "contained_count": containment["contained_polygons_count"],
            "containment_ratio": containment["containment_ratio"],
        },
        "infrastructure_summary": {
            "count_within_radius": infra_proximity["infrastructure_count"],
            "by_type": infra_proximity["infrastructure_by_type"],
            "closest_asset": infra_proximity["closest_infrastructure"],
            "associated_change_area_ha": infra_proximity["associated_change_area_ha"],
            "factual_statements": infra_proximity["factual_summary"],
        },
        "population_summary": {
            "zones_within_radius": pop_proximity["population_zones_count"],
            "intersecting_zones_count": pop_proximity["intersecting_zones_count"],
            "total_intersecting_population": pop_proximity["total_intersecting_population"],
            "factual_statements": pop_proximity["factual_summary"],
        },
    }
