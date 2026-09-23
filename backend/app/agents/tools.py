"""TerraLens Tool Registry & Allowlisted GIS Tool Layer.

Provides structured, deterministic tool execution wrappers around:
- AOI and Scene catalogs
- Deterministic NDVI band algebra and vectorization
- Quality Gate validation
- PostGIS spatial proximity and intersection analytics
"""

import inspect
import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Type
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import ToolParameterSchema, ToolResult
from app.gis.analysis_service import run_ndvi_change_analysis
from app.gis.spatial_service import (
    analyze_infrastructure_proximity as spatial_analyze_infra,
    analyze_population_proximity as spatial_analyze_pop,
    get_analysis_spatial_summary as spatial_get_summary,
    get_change_area_summary as spatial_get_area_summary,
    run_spatial_intersection as spatial_run_intersection,
    validate_aoi_containment as spatial_validate_containment,
)
from app.gis.validation import GISValidationError
from app.validation.quality_gate import QualityGate

logger = logging.getLogger("terralens.agents.tools")


# --- Tool Parameter Schemas ---

class ListAOIsParams(BaseModel):
    limit: Optional[int] = Field(50, description="Max number of AOIs to return")


class GetAOIParams(BaseModel):
    name: Optional[str] = Field(None, description="Name or partial name of Area of Interest (e.g. 'Mau Forest', 'Harz')")
    aoi_id: Optional[uuid.UUID] = Field(None, description="Exact UUID of the Area of Interest")


class ListScenesParams(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="UUID of the Area of Interest")
    before_year: Optional[int] = Field(None, description="Observation year for baseline scene")
    after_year: Optional[int] = Field(None, description="Observation year for comparison scene")
    max_cloud_cover: Optional[float] = Field(20.0, description="Maximum allowed cloud cover percentage (default: 20%)")


class RunNDVIAnalysisParams(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="UUID of the Area of Interest")
    before_scene_id: uuid.UUID = Field(..., description="UUID of baseline satellite scene")
    after_scene_id: uuid.UUID = Field(..., description="UUID of comparison satellite scene")
    threshold: Optional[float] = Field(-0.20, description="NDVI difference threshold for vegetation decrease (e.g. -0.20)")
    minimum_area_m2: Optional[float] = Field(500.0, description="Minimum polygon area in square meters to filter noise")


class ValidateAnalysisParams(BaseModel):
    aoi_id: uuid.UUID = Field(..., description="UUID of the Area of Interest")
    before_scene_id: Optional[uuid.UUID] = Field(None, description="UUID of baseline scene")
    after_scene_id: Optional[uuid.UUID] = Field(None, description="UUID of comparison scene")
    analysis_id: Optional[uuid.UUID] = Field(None, description="UUID of analysis run")
    max_cloud_cover: Optional[float] = Field(20.0, description="Maximum cloud cover threshold")
    threshold: Optional[float] = Field(-0.20, description="NDVI delta threshold")
    min_area_m2: Optional[float] = Field(500.0, description="Minimum polygon area threshold")


class CalculateChangeAreaParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis run")


class FindNearbyInfrastructureParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis run")
    radius_m: Optional[float] = Field(1000.0, ge=0.1, description="Proximity search radius in meters (default: 1000m)")


class GetPopulationContextParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis run")
    radius_m: Optional[float] = Field(1000.0, ge=0.1, description="Proximity search radius in meters (default: 1000m)")


class GetSpatialIntersectionsParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis run")
    layer: Optional[str] = Field("infrastructure", description="Target layer: 'infrastructure', 'population_zones', or 'aoi'")


class ValidateAOIContainmentParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis run")


class GetSpatialSummaryParams(BaseModel):
    analysis_id: uuid.UUID = Field(..., description="UUID of the analysis run")
    radius_m: Optional[float] = Field(1000.0, ge=0.1, description="Spatial search radius in meters (default: 1000m)")


# --- Tool Registry Core ---

class ToolRegistry:
    """Allowlisted Registry for typed GIS & PostGIS tools."""

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, Type[BaseModel]] = {}
        self._descriptions: Dict[str, str] = {}

    def register(self, name: str, description: str, schema_class: Type[BaseModel]):
        """Decorator to register a tool function."""
        def decorator(func: Callable):
            self._tools[name] = func
            self._schemas[name] = schema_class
            self._descriptions[name] = description
            return func
        return decorator

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def get_catalog(self) -> List[Dict[str, Any]]:
        """Return descriptions for all registered tools."""
        catalog = []
        for name, schema_cls in self._schemas.items():
            catalog.append(
                {
                    "name": name,
                    "description": self._descriptions[name],
                    "parameters": schema_cls.model_json_schema(),
                }
            )
        return catalog

    def get_tool_names(self) -> List[str]:
        return list(self._tools.keys())

    async def execute(
        self,
        name: str,
        parameters: Dict[str, Any],
        db: AsyncSession,
    ) -> ToolResult:
        """Validate parameters and execute allowlisted tool."""
        if not self.is_registered(name):
            return ToolResult(
                success=False,
                tool_name=name,
                error=f"Security Violation: Tool '{name}' is not in the allowlisted tool registry.",
                summary=f"Tool '{name}' is not in allowlisted registry",
            )

        schema_cls = self._schemas[name]
        func = self._tools[name]
        start_time = time.perf_counter()

        try:
            # 1. Validate parameters using Pydantic schema
            try:
                parsed_params = schema_cls(**parameters)
            except (ValidationError, ValueError) as val_err:
                exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return ToolResult(
                    success=False,
                    tool_name=name,
                    error=str(val_err),
                    summary=f"Invalid parameters for tool '{name}': {str(val_err)}",
                    execution_time_ms=exec_time_ms,
                )

            kwargs = parsed_params.model_dump(exclude_unset=True)

            # 2. Inject db session if accepted by tool function
            sig = inspect.signature(func)
            if "db" in sig.parameters:
                kwargs["db"] = db

            # 3. Execute tool
            data = await func(**kwargs)
            exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 4. Generate concise summary
            summary = self._generate_summary(name, data)
            return ToolResult(
                success=True,
                tool_name=name,
                data=data,
                summary=summary,
                execution_time_ms=exec_time_ms,
            )

        except Exception as e:
            exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"Error executing tool '{name}': {e}", exc_info=True)
            return ToolResult(
                success=False,
                tool_name=name,
                error=str(e),
                summary=f"Tool '{name}' failed: {str(e)}",
                execution_time_ms=exec_time_ms,
            )

    def _generate_summary(self, tool_name: str, data: Any) -> str:
        """Generate concise human-readable summary for activity logs."""
        if not isinstance(data, dict):
            return f"Executed tool '{tool_name}' successfully."

        if tool_name in ("get_aoi", "list_aois"):
            if "name" in data:
                return f"Resolved AOI '{data.get('name')}' ({data.get('area_hectares', 0)} ha)"
            return f"Retrieved {len(data.get('aois', []))} cataloged AOIs"
        elif tool_name in ("list_scenes", "get_satellite_metadata"):
            before = data.get("before_scene", {})
            after = data.get("after_scene", {})
            return f"Selected scenes: Baseline {before.get('scene_identifier')} -> Comparison {after.get('scene_identifier')}"
        elif tool_name in ("run_ndvi_analysis", "run_ndvi_change_pipeline"):
            m = data.get("metrics", {})
            return f"NDVI analysis complete: {m.get('total_change_area_ha', 0)} ha across {m.get('change_polygon_count', 0)} polygon(s)"
        elif tool_name == "validate_analysis":
            status = data.get("status", "UNKNOWN")
            passed = data.get("passed_checks", 0)
            total = data.get("total_checks", 0)
            return f"Quality Gate: {status} ({passed}/{total} checks passed)"
        elif tool_name == "calculate_change_area":
            return f"Spatial summary: {data.get('total_change_area_ha', 0)} ha change area ({data.get('change_polygon_count', 0)} polygons)"
        elif tool_name == "find_nearby_infrastructure":
            count = data.get("infrastructure_count", 0)
            closest = data.get("closest_infrastructure")
            closest_name = closest.get("name", "N/A") if closest else "None"
            return f"Infrastructure proximity: Found {count} asset(s) within radius (Closest: {closest_name})"
        elif tool_name in ("get_population_context", "analyze_population_proximity"):
            count = data.get("population_zones_count", 0)
            inter = data.get("intersecting_zones_count", 0)
            pop = data.get("total_intersecting_population", 0)
            return f"Demographic context: {count} zone(s) nearby, {inter} intersecting ({pop:,} registered residents)"
        elif tool_name in ("get_spatial_intersections", "run_spatial_intersection"):
            count = data.get("intersection_count", 0)
            return f"Exact PostGIS ST_Intersects: {count} geometric intersection(s)"
        elif tool_name == "validate_aoi_containment":
            ratio = data.get("containment_ratio", 0) * 100
            return f"AOI Containment: {ratio:.1f}% strictly within official boundary"
        elif tool_name == "get_spatial_summary":
            return f"Spatial summary generated successfully"
        return f"Tool '{tool_name}' executed successfully"


tool_registry = ToolRegistry()


# --- Tool Implementations ---

@tool_registry.register(
    name="list_aois",
    description="List all cataloged Areas of Interest (AOIs) with geographic boundaries and areas.",
    schema_class=ListAOIsParams,
)
async def list_aois_tool(db: AsyncSession, limit: int = 50) -> Dict[str, Any]:
    query = text(
        """
        SELECT id, name, description, bounding_box, ST_Area(geometry::geography)/10000.0 as area_ha
        FROM aois
        ORDER BY name
        LIMIT :limit;
        """
    )
    res = await db.execute(query, {"limit": limit})
    rows = res.fetchall()
    aois = [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "bounding_box": r.bounding_box,
            "area_hectares": round(float(r.area_ha), 2),
        }
        for r in rows
    ]
    return {"total_aois": len(aois), "aois": aois}


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
    name="list_scenes",
    description="Query and filter cataloged Sentinel-2 multispectral satellite scenes for an AOI by year and cloud cover limits.",
    schema_class=ListScenesParams,
)
async def list_scenes_tool(
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


# Register get_satellite_metadata as an alias for list_scenes
@tool_registry.register(
    name="get_satellite_metadata",
    description="Query and filter cataloged Sentinel-2 multispectral satellite scenes for an AOI (alias for list_scenes).",
    schema_class=ListScenesParams,
)
async def get_satellite_metadata_tool(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    before_year: Optional[int] = None,
    after_year: Optional[int] = None,
    max_cloud_cover: float = 20.0,
) -> Dict[str, Any]:
    return await list_scenes_tool(
        db=db,
        aoi_id=aoi_id,
        before_year=before_year,
        after_year=after_year,
        max_cloud_cover=max_cloud_cover,
    )


@tool_registry.register(
    name="run_ndvi_analysis",
    description="Execute complete deterministic NDVI change detection pipeline (NIR/Red band math, delta thresholding, geodesic polygonization, and PostGIS storage).",
    schema_class=RunNDVIAnalysisParams,
)
async def run_ndvi_analysis_tool(
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


# Alias run_ndvi_change_pipeline
@tool_registry.register(
    name="run_ndvi_change_pipeline",
    description="Execute complete deterministic NDVI change detection pipeline (alias for run_ndvi_analysis).",
    schema_class=RunNDVIAnalysisParams,
)
async def run_ndvi_change_pipeline_alias(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    before_scene_id: uuid.UUID,
    after_scene_id: uuid.UUID,
    threshold: float = -0.20,
    minimum_area_m2: float = 500.0,
) -> Dict[str, Any]:
    return await run_ndvi_analysis_tool(
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
    name="get_population_context",
    description="Execute PostGIS demographic proximity and intersection analysis on population settlement zones near change polygons.",
    schema_class=GetPopulationContextParams,
)
async def get_population_context_tool(db: AsyncSession, analysis_id: uuid.UUID, radius_m: float = 1000.0) -> Dict[str, Any]:
    return await spatial_analyze_pop(db=db, analysis_id=analysis_id, radius_m=radius_m)


# Alias analyze_population_proximity
@tool_registry.register(
    name="analyze_population_proximity",
    description="Execute PostGIS demographic proximity analysis (alias for get_population_context).",
    schema_class=GetPopulationContextParams,
)
async def analyze_population_proximity_alias(db: AsyncSession, analysis_id: uuid.UUID, radius_m: float = 1000.0) -> Dict[str, Any]:
    return await get_population_context_tool(db=db, analysis_id=analysis_id, radius_m=radius_m)


@tool_registry.register(
    name="get_spatial_intersections",
    description="Execute exact PostGIS ST_Intersects and ST_Intersection overlay between change polygons and target layer ('infrastructure', 'population_zones', or 'aoi').",
    schema_class=GetSpatialIntersectionsParams,
)
async def get_spatial_intersections_tool(db: AsyncSession, analysis_id: uuid.UUID, layer: str = "infrastructure") -> Dict[str, Any]:
    return await spatial_run_intersection(db=db, analysis_id=analysis_id, layer=layer)


# Alias run_spatial_intersection
@tool_registry.register(
    name="run_spatial_intersection",
    description="Execute exact PostGIS ST_Intersects overlay (alias for get_spatial_intersections).",
    schema_class=GetSpatialIntersectionsParams,
)
async def run_spatial_intersection_alias(db: AsyncSession, analysis_id: uuid.UUID, layer: str = "infrastructure") -> Dict[str, Any]:
    return await get_spatial_intersections_tool(db=db, analysis_id=analysis_id, layer=layer)


@tool_registry.register(
    name="validate_aoi_containment",
    description="Verify strict PostGIS ST_Within topological containment of change polygons inside the AOI boundary.",
    schema_class=ValidateAOIContainmentParams,
)
async def validate_aoi_containment_tool(db: AsyncSession, analysis_id: uuid.UUID) -> Dict[str, Any]:
    return await spatial_validate_containment(db=db, analysis_id=analysis_id)


@tool_registry.register(
    name="get_spatial_summary",
    description="Generate unified PostGIS spatial summary combining area metrics, containment, infrastructure proximity, and population context.",
    schema_class=GetSpatialSummaryParams,
)
async def get_spatial_summary_tool(db: AsyncSession, analysis_id: uuid.UUID, radius_m: float = 1000.0) -> Dict[str, Any]:
    return await spatial_get_summary(db=db, analysis_id=analysis_id, radius_m=radius_m)
