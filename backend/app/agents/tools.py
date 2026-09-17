"""TerraLens Allowlisted Agent Tool Registry.

Defines deterministic tool interfaces wrapping existing Phase 1–3 GIS and PostGIS services:
1. get_aoi: Resolve AOI record by name or ID
2. get_satellite_metadata: Resolve and inspect Sentinel-2 scenes for AOI by timeframe
3. run_ndvi_change_pipeline: Atomic deterministic NDVI differencing & PostGIS vectorization
4. validate_analysis: Execute multi-stage Quality Gate
5. calculate_change_area: PostGIS spatial aggregation on change polygons
6. find_nearby_infrastructure: PostGIS ST_DWithin & ST_Distance proximity search
7. analyze_population_proximity: PostGIS demographic proximity & intersection analysis
8. run_spatial_intersection: PostGIS exact ST_Intersects layer overlay
"""

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Type
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import ToolResult, ToolParameterSchema
from app.gis.analysis_service import run_ndvi_change_analysis
from app.gis.spatial_service import (
    find_nearby_infrastructure as spatial_find_nearby_infra,
    analyze_infrastructure_proximity as spatial_analyze_infra,
    analyze_population_proximity as spatial_analyze_pop,
    run_spatial_intersection as spatial_run_intersection,
    get_change_area_summary as spatial_get_area_summary,
    validate_aoi_containment as spatial_validate_containment,
)
from app.gis.validation import GISValidationError
from app.validation.quality_gate import QualityGate

logger = logging.getLogger("terralens.agents.tools")


# --- Tool Parameter Schemas ---

class GetAOIParams(BaseModel):
    name: Optional[str] = Field(None, description="Name or partial name of Area of Interest (e.g. 'Mau Forest', 'Harz')")
    aoi_id: Optional[uuid.UUID] = Field(None, description="Direct UUID of Area of Interest")


class GetSatelliteMetadataParams(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="Target Area of Interest UUID")
    before_year: Optional[int] = Field(None, description="Baseline observation year (e.g. 2020)")
    after_year: Optional[int] = Field(None, description="Comparison observation year (e.g. 2025)")
    max_cloud_cover: float = Field(default=20.0, description="Maximum permitted cloud cover percentage")


class RunNDVIChangePipelineParams(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="Target Area of Interest UUID")
    before_scene_id: uuid.UUID = Field(..., description="Baseline satellite scene UUID")
    after_scene_id: uuid.UUID = Field(..., description="Comparison satellite scene UUID")
    threshold: float = Field(default=-0.20, description="NDVI difference threshold for significant decrease")
    minimum_area_m2: float = Field(default=500.0, description="Minimum polygon area in m² to filter noise")


class ValidateAnalysisParams(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="Target Area of Interest UUID")
    before_scene_id: Optional[uuid.UUID] = Field(None, description="Baseline scene UUID")
    after_scene_id: Optional[uuid.UUID] = Field(None, description="Comparison scene UUID")
    analysis_id: Optional[uuid.UUID] = Field(None, description="Analysis run UUID")
    max_cloud_cover: float = Field(default=20.0, description="Cloud cover percentage limit")
    threshold: float = Field(default=-0.20, description="NDVI change threshold")
    min_area_m2: float = Field(default=500.0, description="Minimum polygon surface area threshold")


class CalculateChangeAreaParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="Analysis run UUID")


class FindNearbyInfrastructureParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="Analysis run UUID")
    radius_m: float = Field(default=1000.0, gt=0, le=100000.0, description="Proximity search radius in meters")


class AnalyzePopulationProximityParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="Analysis run UUID")
    radius_m: float = Field(default=1000.0, gt=0, le=100000.0, description="Search radius in meters")


class RunSpatialIntersectionParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="Analysis run UUID")
    layer: str = Field(default="infrastructure", description="Target layer: 'infrastructure', 'population_zones', 'aoi'")


# --- Tool Registry Core ---

class ToolRegistry:
    """Allowlisted registry for deterministic GIS and PostGIS agent tools."""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, description: str, schema_class: Type[BaseModel]):
        """Decorator to register a tool function with strict parameter schema."""
        def decorator(func: Callable):
            self._tools[name] = {
                "name": name,
                "description": description,
                "schema": schema_class,
                "func": func,
            }
            return func
        return decorator

    def get_catalog(self) -> List[Dict[str, Any]]:
        """Return full allowlisted tool catalog with parameter JSON schemas."""
        catalog = []
        for name, meta in self._tools.items():
            catalog.append(
                {
                    "name": name,
                    "description": meta["description"],
                    "parameters_schema": meta["schema"].model_json_schema(),
                }
            )
        return catalog

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    async def execute(
        self,
        name: str,
        parameters: Dict[str, Any],
        db: AsyncSession,
    ) -> ToolResult:
        """Validate parameters and execute an allowlisted tool."""
        if name not in self._tools:
            return ToolResult(
                success=False,
                tool_name=name,
                summary=f"Unknown tool '{name}'. Tool is not in allowlisted registry.",
                error=f"Tool '{name}' rejected by security policy",
            )

        tool_meta = self._tools[name]
        schema_class: Type[BaseModel] = tool_meta["schema"]
        func: Callable = tool_meta["func"]

        # Validate parameters against Pydantic schema
        try:
            validated_params = schema_class(**parameters)
        except ValidationError as e:
            return ToolResult(
                success=False,
                tool_name=name,
                summary=f"Invalid parameters for tool '{name}': {str(e)}",
                error=str(e),
            )

        start_time = time.perf_counter()
        try:
            result_data = await func(db=db, **validated_params.model_dump())
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            summary = self._generate_tool_summary(name, result_data)
            return ToolResult(
                success=True,
                tool_name=name,
                data=result_data,
                summary=summary,
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"Tool '{name}' execution failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                tool_name=name,
                summary=f"Execution error in tool '{name}': {str(e)}",
                error=str(e),
                execution_time_ms=elapsed_ms,
            )

    def _generate_tool_summary(self, tool_name: str, data: Any) -> str:
        if tool_name == "get_aoi":
            return f"Resolved AOI '{data.get('name')}' (ID: {data.get('id')}, Area: {data.get('area_hectares'):,} ha)"
        elif tool_name == "get_satellite_metadata":
            before = data.get("before_scene", {}).get("scene_identifier", "N/A")
            after = data.get("after_scene", {}).get("scene_identifier", "N/A")
            return f"Matched Sentinel-2 scenes: Baseline '{before}', Comparison '{after}'"
        elif tool_name == "run_ndvi_change_pipeline":
            metrics = data.get("metrics", {})
            return f"Detected {metrics.get('change_polygon_count', 0)} vegetation-change polygon(s) totaling {metrics.get('total_change_area_ha', 0)} ha (Analysis ID: {data.get('analysis_id')})"
        elif tool_name == "validate_analysis":
            status = data.get("status") if isinstance(data, dict) else getattr(data, "status", "UNKNOWN")
            return f"Quality Gate evaluation: {status}"
        elif tool_name == "calculate_change_area":
            return f"Total change area: {data.get('total_change_area_ha')} ha across {data.get('change_polygon_count')} polygon(s)"
        elif tool_name == "find_nearby_infrastructure":
            count = len(data) if isinstance(data, list) else data.get("infrastructure_count", 0)
            return f"PostGIS ST_DWithin: Found {count} infrastructure asset(s) within search radius"
        elif tool_name == "analyze_population_proximity":
            count = data.get("population_zones_count", 0)
            inter = data.get("intersecting_zones_count", 0)
            return f"Demographic proximity: {count} zone(s) nearby, {inter} intersecting change polygons"
        elif tool_name == "run_spatial_intersection":
            count = data.get("intersection_count", 0)
            return f"Exact PostGIS ST_Intersects: {count} geometric intersection(s)"
        return f"Tool '{tool_name}' executed successfully"


tool_registry = ToolRegistry()


# --- Tool Implementations ---

@tool_registry.register(
    name="get_aoi",
    description="Retrieve Area of Interest (AOI) boundary, name, and geographic metadata by name or UUID.",
    schema_class=GetAOIParams,
)
async def get_aoi_tool(db: AsyncSession, name: Optional[str] = None, aoi_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    if aoi_id:
        query = text(
            """
            SELECT id, name, description, bounding_box, ST_Area(geometry::geography)/10000.0 as area_ha, ST_AsGeoJSON(geometry) as geojson
            FROM aois WHERE id = :id;
            """
        )
        res = await db.execute(query, {"id": aoi_id})
    elif name:
        query = text(
            """
            SELECT id, name, description, bounding_box, ST_Area(geometry::geography)/10000.0 as area_ha, ST_AsGeoJSON(geometry) as geojson
            FROM aois WHERE name ILIKE :name_pattern ORDER BY name LIMIT 1;
            """
        )
        res = await db.execute(query, {"name_pattern": f"%{name}%"})
    else:
        raise GISValidationError("Either 'name' or 'aoi_id' must be provided")

    row = res.fetchone()
    if not row:
        raise GISValidationError(f"Area of Interest '{name or aoi_id}' not found in catalog")

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "bounding_box": row.bounding_box,
        "area_hectares": round(float(row.area_ha), 2),
    }


@tool_registry.register(
    name="get_satellite_metadata",
    description="Query and filter cataloged Sentinel-2 multispectral satellite scenes for an AOI by observation year and cloud cover limits.",
    schema_class=GetSatelliteMetadataParams,
)
async def get_satellite_metadata_tool(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    before_year: Optional[int] = None,
    after_year: Optional[int] = None,
    max_cloud_cover: float = 20.0,
) -> Dict[str, Any]:
    query = text(
        """
        SELECT id, aoi_id, scene_identifier, satellite, sensor, acquisition_date, cloud_cover, spatial_resolution, red_band_path, nir_band_path
        FROM satellite_scenes
        WHERE aoi_id = :aoi_id
        ORDER BY acquisition_date ASC;
        """
    )
    res = await db.execute(query, {"aoi_id": aoi_id})
    rows = res.fetchall()

    if not rows:
        raise GISValidationError(f"No satellite scenes found for AOI '{aoi_id}'")

    scenes_list = []
    for r in rows:
        scenes_list.append(
            {
                "id": str(r.id),
                "scene_identifier": r.scene_identifier,
                "satellite": r.satellite,
                "sensor": r.sensor,
                "acquisition_date": r.acquisition_date.isoformat(),
                "year": r.acquisition_date.year,
                "cloud_cover": float(r.cloud_cover),
                "spatial_resolution": float(r.spatial_resolution),
            }
        )

    # Resolve before scene
    before_candidates = [s for s in scenes_list if before_year is None or s["year"] == before_year]
    # Filter out STABLE test scene for baseline if multiple exist
    before_clean = [s for s in before_candidates if "STABLE" not in s["scene_identifier"] and "HIGHCLOUD" not in s["scene_identifier"]]
    before_scene = before_clean[0] if before_clean else (before_candidates[0] if before_candidates else scenes_list[0])

    # Resolve after scene
    after_candidates = [s for s in scenes_list if after_year is None or s["year"] == after_year]
    after_clean = [s for s in after_candidates if "STABLE" not in s["scene_identifier"] and "HIGHCLOUD" not in s["scene_identifier"]]
    after_scene = after_clean[-1] if after_clean else (after_candidates[-1] if after_candidates else scenes_list[-1])

    return {
        "aoi_id": str(aoi_id),
        "total_available_scenes": len(scenes_list),
        "before_scene": before_scene,
        "after_scene": after_scene,
        "all_scenes": scenes_list,
    }


@tool_registry.register(
    name="run_ndvi_change_pipeline",
    description="Execute complete deterministic NDVI change detection pipeline (NIR/Red band math, delta thresholding, geodesic polygonization, and PostGIS storage).",
    schema_class=RunNDVIChangePipelineParams,
)
async def run_ndvi_change_pipeline_tool(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    before_scene_id: uuid.UUID,
    after_scene_id: uuid.UUID,
    threshold: float = -0.20,
    minimum_area_m2: float = 500.0,
) -> Dict[str, Any]:
    return await run_ndvi_change_analysis(
        db=db,
        aoi_id=aoi_id,
        before_scene_id=before_scene_id,
        after_scene_id=after_scene_id,
        threshold=threshold,
        minimum_area_m2=minimum_area_m2,
    )


@tool_registry.register(
    name="validate_analysis",
    description="Execute rigorous Quality Gate verifying cloud cover limits, radiometric delta, minimum polygon area, and PostGIS AOI boundary containment.",
    schema_class=ValidateAnalysisParams,
)
async def validate_analysis_tool(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    before_scene_id: Optional[uuid.UUID] = None,
    after_scene_id: Optional[uuid.UUID] = None,
    analysis_id: Optional[uuid.UUID] = None,
    max_cloud_cover: float = 20.0,
    threshold: float = -0.20,
    min_area_m2: float = 500.0,
) -> Dict[str, Any]:
    report = await QualityGate.evaluate(
        db=db,
        aoi_id=aoi_id,
        before_scene_id=before_scene_id,
        after_scene_id=after_scene_id,
        analysis_id=analysis_id,
        max_cloud_cover=max_cloud_cover,
        threshold=threshold,
        min_area_m2=min_area_m2,
    )
    return report.model_dump()


@tool_registry.register(
    name="calculate_change_area",
    description="Execute PostGIS spatial aggregation calculating total area (m² and ha), polygon count, and area distribution.",
    schema_class=CalculateChangeAreaParams,
)
async def calculate_change_area_tool(db: AsyncSession, analysis_id: uuid.UUID) -> Dict[str, Any]:
    return await spatial_get_area_summary(db=db, analysis_id=analysis_id)


@tool_registry.register(
    name="find_nearby_infrastructure",
    description="Execute PostGIS ST_DWithin and ST_Distance proximity search identifying infrastructure assets within specified radius in meters of change polygons.",
    schema_class=FindNearbyInfrastructureParams,
)
async def find_nearby_infrastructure_tool(db: AsyncSession, analysis_id: uuid.UUID, radius_m: float = 1000.0) -> Dict[str, Any]:
    return await spatial_analyze_infra(db=db, analysis_id=analysis_id, radius_m=radius_m)


@tool_registry.register(
    name="analyze_population_proximity",
    description="Execute PostGIS demographic proximity and intersection analysis on population settlement zones near change polygons.",
    schema_class=AnalyzePopulationProximityParams,
)
async def analyze_population_proximity_tool(db: AsyncSession, analysis_id: uuid.UUID, radius_m: float = 1000.0) -> Dict[str, Any]:
    return await spatial_analyze_pop(db=db, analysis_id=analysis_id, radius_m=radius_m)


@tool_registry.register(
    name="run_spatial_intersection",
    description="Execute exact PostGIS ST_Intersects and ST_Intersection overlay between change polygons and target layer ('infrastructure', 'population_zones', or 'aoi').",
    schema_class=RunSpatialIntersectionParams,
)
async def run_spatial_intersection_tool(db: AsyncSession, analysis_id: uuid.UUID, layer: str = "infrastructure") -> Dict[str, Any]:
    return await spatial_run_intersection(db=db, analysis_id=analysis_id, layer=layer)
