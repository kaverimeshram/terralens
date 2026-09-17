"""TerraLens Phase 3 Automated Test Suite - PostGIS Spatial Intelligence Engine.

Verifies:
1. PostGIS ST_DWithin & ST_Distance proximity queries against change polygons.
2. PostGIS ST_Distance calculation accuracy and distance ordering.
3. PostGIS ST_Intersects & ST_Intersection with infrastructure layer.
4. PostGIS ST_Intersects & ST_Intersection with population zones layer (area calculations).
5. PostGIS ST_Intersects with AOI boundary.
6. AOI containment validation query (ST_Within & containment ratio).
7. Spatial aggregation service (SUM ST_Area, COUNT, min/max/mean polygon area).
8. Empty result handling when no infrastructure is within the specified radius.
9. Population zone proximity & intersection queries.
10. Unified spatial summary service combining all PostGIS capabilities.
11. FastAPI GET /api/analysis/{id}/nearby-infrastructure endpoint (JSON format).
12. FastAPI GET /api/analysis/{id}/nearby-infrastructure endpoint (GeoJSON format).
13. FastAPI GET /api/analysis/{id}/spatial-summary endpoint.
14. FastAPI GET /api/analysis/{id}/population-context endpoint (JSON & GeoJSON).
15. FastAPI GET /api/analysis/{id}/spatial-intersection endpoint.
16. FastAPI GET /api/analysis/{id}/aoi-containment endpoint.
17. API error handling for non-existent analysis run ID (404 Not Found).
18. API error handling for invalid proximity radius (400/422 Bad Request).
19. Demonstration scenario: Eastern Mau Forest 2020 -> 2025 analysis with 1 km proximity query.
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.database.session import AsyncSessionLocal
from app.gis.analysis_service import run_ndvi_change_analysis
from app.gis.spatial_service import (
    find_nearby_infrastructure,
    analyze_infrastructure_proximity,
    analyze_population_proximity,
    run_spatial_intersection,
    get_change_area_summary,
    validate_aoi_containment,
    get_analysis_spatial_summary,
)
from app.gis.validation import GISValidationError


async def get_or_create_mau_analysis() -> uuid.UUID:
    """Helper returning a completed Mau Forest 2020 -> 2025 analysis run ID."""
    async with AsyncSessionLocal() as db:
        q = text(
            """
            SELECT id FROM analysis_runs 
            WHERE aoi_id = 'a0000000-0000-0000-0000-000000000001'
              AND before_scene_id = 'b0000000-0000-0000-0000-000000000001'
              AND after_scene_id = 'b0000000-0000-0000-0000-000000000002'
            ORDER BY created_at DESC LIMIT 1;
            """
        )
        res = await db.execute(q)
        row = res.fetchone()
        if row:
            return row.id

        result = await run_ndvi_change_analysis(
            db=db,
            aoi_id=uuid.UUID("a0000000-0000-0000-0000-000000000001"),
            before_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000001"),
            after_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000002"),
            threshold=-0.20,
            minimum_area_m2=500.0,
        )
        return uuid.UUID(result["analysis_id"])


async def get_or_create_harz_analysis() -> uuid.UUID:
    """Helper returning a completed Harz National Park analysis run ID."""
    async with AsyncSessionLocal() as db:
        q = text(
            """
            SELECT id FROM analysis_runs 
            WHERE aoi_id = 'a0000000-0000-0000-0000-000000000002'
            ORDER BY created_at DESC LIMIT 1;
            """
        )
        res = await db.execute(q)
        row = res.fetchone()
        if row:
            return row.id

        result = await run_ndvi_change_analysis(
            db=db,
            aoi_id=uuid.UUID("a0000000-0000-0000-0000-000000000002"),
            before_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000005"),
            after_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000006"),
            threshold=-0.20,
            minimum_area_m2=500.0,
        )
        return uuid.UUID(result["analysis_id"])


# --- 1. PostGIS ST_DWithin & ST_Distance Spatial Proximity ---

@pytest.mark.asyncio
async def test_postgis_stdwithin_infrastructure_query():
    """Verify find_nearby_infrastructure queries PostGIS correctly with ST_DWithin and ST_Distance."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        items = await find_nearby_infrastructure(db=db, analysis_id=analysis_id, radius_m=1000.0)
        assert len(items) > 0
        for item in items:
            assert "id" in item
            assert "name" in item
            assert "type" in item
            assert "distance_m" in item
            assert "nearest_change_polygon_id" in item
            assert "change_polygon_area_m2" in item
            assert item["distance_m"] <= 1000.0


# --- 2. PostGIS ST_Distance Accuracy & Ordering ---

@pytest.mark.asyncio
async def test_postgis_stdistance_accuracy():
    """Verify returned infrastructure items are sorted strictly in ascending order by PostGIS distance."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        items = await find_nearby_infrastructure(db=db, analysis_id=analysis_id, radius_m=5000.0)
        assert len(items) >= 2
        distances = [item["distance_m"] for item in items]
        assert distances == sorted(distances), "Results must be sorted by PostGIS distance_m ASC"
        assert distances[0] == 0.0


# --- 3. PostGIS ST_Intersects with Infrastructure ---

@pytest.mark.asyncio
async def test_postgis_stintersects_layer_infrastructure():
    """Verify run_spatial_intersection with infrastructure layer."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        result = await run_spatial_intersection(db=db, analysis_id=analysis_id, layer="infrastructure")
        assert result["layer"] == "infrastructure"
        assert result["intersection_count"] > 0
        first_inter = result["intersections"][0]
        assert "change_polygon_id" in first_inter
        assert "feature_name" in first_inter
        assert "feature_type" in first_inter
        assert "intersection_geometry" in first_inter
        assert first_inter["distance_m"] == 0.0


# --- 4. PostGIS ST_Intersects with Population Zones ---

@pytest.mark.asyncio
async def test_postgis_stintersects_layer_population():
    """Verify run_spatial_intersection with population_zones layer computes exact intersection area."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        result = await run_spatial_intersection(db=db, analysis_id=analysis_id, layer="population_zones")
        assert result["layer"] == "population_zones"
        assert "intersections" in result
        for inter in result["intersections"]:
            assert "population" in inter
            assert "intersection_area_m2" in inter
            assert "intersection_area_ha" in inter
            assert inter["intersection_area_m2"] >= 0.0


# --- 5. PostGIS ST_Intersects with AOI ---

@pytest.mark.asyncio
async def test_postgis_stintersects_layer_aoi():
    """Verify run_spatial_intersection with aoi layer."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        result = await run_spatial_intersection(db=db, analysis_id=analysis_id, layer="aoi")
        assert result["layer"] == "aoi"
        assert result["intersection_count"] > 0
        for inter in result["intersections"]:
            assert inter["is_strictly_within"] is True
            assert inter["intersection_area_m2"] > 0.0


# --- 6. AOI Containment Validation ---

@pytest.mark.asyncio
async def test_aoi_containment_validation():
    """Verify validate_aoi_containment confirms all detected polygons are contained within the AOI."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        containment = await validate_aoi_containment(db=db, analysis_id=analysis_id)
        assert containment["all_polygons_contained"] is True
        assert containment["total_polygons"] > 0
        assert containment["contained_polygons_count"] == containment["total_polygons"]
        assert containment["outside_polygons_count"] == 0
        assert containment["containment_ratio"] >= 0.999


# --- 7. Spatial Aggregation Summary ---

@pytest.mark.asyncio
async def test_spatial_aggregation_summary():
    """Verify get_change_area_summary calculates accurate aggregate statistics."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        summary = await get_change_area_summary(db=db, analysis_id=analysis_id)
        assert summary["change_polygon_count"] > 0
        assert summary["total_change_area_m2"] > 0.0
        assert summary["total_change_area_ha"] > 0.0
        assert summary["min_polygon_area_m2"] >= 500.0
        assert summary["max_polygon_area_m2"] >= summary["min_polygon_area_m2"]
        assert summary["mean_polygon_area_m2"] >= summary["min_polygon_area_m2"]
        assert summary["mean_ndvi_change"] < -0.20


# --- 8. Infrastructure Proximity with Empty Radius ---

@pytest.mark.asyncio
async def test_infrastructure_proximity_empty_radius():
    """Verify search returns clean empty results when no infrastructure is in radius."""
    harz_id = await get_or_create_harz_analysis()
    async with AsyncSessionLocal() as db:
        # At 100m, Brocken station (508m away) is out of range
        analysis = await analyze_infrastructure_proximity(db=db, analysis_id=harz_id, radius_m=100.0)
        assert analysis["infrastructure_count"] == 0
        assert len(analysis["infrastructure"]) == 0
        assert analysis["closest_infrastructure"] is None
        assert "No infrastructure assets found" in analysis["factual_summary"][0]


# --- 9. Population Proximity Analysis ---

@pytest.mark.asyncio
async def test_population_proximity_analysis():
    """Verify analyze_population_proximity returns structured demographic context."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        pop_res = await analyze_population_proximity(db=db, analysis_id=analysis_id, radius_m=5000.0)
        assert pop_res["population_zones_count"] > 0
        assert len(pop_res["zones"]) > 0
        first_zone = pop_res["zones"][0]
        assert "name" in first_zone
        assert "population" in first_zone
        assert "distance_m" in first_zone
        assert "intersects_change" in first_zone


# --- 10. Unified Spatial Summary Service ---

@pytest.mark.asyncio
async def test_unified_spatial_summary_service():
    """Verify get_analysis_spatial_summary integrates change metrics, containment, infra, and population."""
    analysis_id = await get_or_create_mau_analysis()
    async with AsyncSessionLocal() as db:
        summary = await get_analysis_spatial_summary(db=db, analysis_id=analysis_id, radius_m=1000.0)
        assert "change_metrics" in summary
        assert "aoi_containment" in summary
        assert "infrastructure_summary" in summary
        assert "population_summary" in summary
        assert summary["aoi_containment"]["all_contained"] is True
        assert summary["infrastructure_summary"]["count_within_radius"] > 0


# --- 11. API GET /nearby-infrastructure (JSON) ---

@pytest.mark.asyncio
async def test_api_nearby_infrastructure_endpoint():
    """Verify GET /api/analysis/{id}/nearby-infrastructure endpoint."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/analysis/{analysis_id}/nearby-infrastructure?radius_m=1000")
        assert res.status_code == 200
        data = res.json()
        assert data["analysis_id"] == str(analysis_id)
        assert data["radius_m"] == 1000.0
        assert data["infrastructure_count"] > 0
        assert len(data["infrastructure"]) == data["infrastructure_count"]
        first_item = data["infrastructure"][0]
        assert "name" in first_item
        assert "type" in first_item
        assert "distance_m" in first_item


# --- 12. API GET /nearby-infrastructure (GeoJSON) ---

@pytest.mark.asyncio
async def test_api_nearby_infrastructure_geojson():
    """Verify GET /api/analysis/{id}/nearby-infrastructure?format=geojson returns valid FeatureCollection."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/analysis/{analysis_id}/nearby-infrastructure?radius_m=1000&format=geojson")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "FeatureCollection"
        assert data["count"] > 0
        assert len(data["features"]) == data["count"]
        first_feat = data["features"][0]
        assert "geometry" in first_feat
        assert "properties" in first_feat
        assert "distance_m" in first_feat["properties"]


# --- 13. API GET /spatial-summary ---

@pytest.mark.asyncio
async def test_api_spatial_summary_endpoint():
    """Verify GET /api/analysis/{id}/spatial-summary endpoint."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/analysis/{analysis_id}/spatial-summary?radius_m=1000")
        assert res.status_code == 200
        data = res.json()
        assert data["analysis_id"] == str(analysis_id)
        assert "change_metrics" in data
        assert "aoi_containment" in data
        assert "infrastructure_summary" in data
        assert "population_summary" in data


# --- 14. API GET /population-context ---

@pytest.mark.asyncio
async def test_api_population_context_endpoint():
    """Verify GET /api/analysis/{id}/population-context endpoint (JSON & GeoJSON)."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # JSON format
        res_json = await ac.get(f"/api/analysis/{analysis_id}/population-context?radius_m=3000")
        assert res_json.status_code == 200
        data_json = res_json.json()
        assert "population_zones_count" in data_json
        assert "zones" in data_json

        # GeoJSON format
        res_geo = await ac.get(f"/api/analysis/{analysis_id}/population-context?radius_m=3000&format=geojson")
        assert res_geo.status_code == 200
        data_geo = res_geo.json()
        assert data_geo["type"] == "FeatureCollection"


# --- 15. API GET /spatial-intersection ---

@pytest.mark.asyncio
async def test_api_spatial_intersection_endpoint():
    """Verify GET /api/analysis/{id}/spatial-intersection endpoint."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/analysis/{analysis_id}/spatial-intersection?layer=infrastructure")
        assert res.status_code == 200
        data = res.json()
        assert data["layer"] == "infrastructure"
        assert "intersections" in data


# --- 16. API GET /aoi-containment ---

@pytest.mark.asyncio
async def test_api_aoi_containment_endpoint():
    """Verify GET /api/analysis/{id}/aoi-containment endpoint."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/analysis/{analysis_id}/aoi-containment")
        assert res.status_code == 200
        data = res.json()
        assert data["all_polygons_contained"] is True
        assert data["total_polygons"] > 0


# --- 17. API Error Handling: Invalid Analysis ID ---

@pytest.mark.asyncio
async def test_api_error_handling_invalid_analysis_id():
    """Verify 404 response when querying non-existent analysis ID."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        fake_id = str(uuid.uuid4())
        res = await ac.get(f"/api/analysis/{fake_id}/nearby-infrastructure?radius_m=1000")
        assert res.status_code == 404

        res2 = await ac.get(f"/api/analysis/{fake_id}/spatial-summary")
        assert res2.status_code == 404


# --- 18. API Error Handling: Invalid Radius ---

@pytest.mark.asyncio
async def test_api_error_handling_invalid_radius():
    """Verify 400/422 response when passing non-positive radius."""
    analysis_id = await get_or_create_mau_analysis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/analysis/{analysis_id}/nearby-infrastructure?radius_m=-50")
        assert res.status_code in (400, 422)

        res2 = await ac.get(f"/api/analysis/{analysis_id}/nearby-infrastructure?radius_m=0")
        assert res2.status_code in (400, 422)


# --- 19. Demonstration Scenario: Mau Forest 2020 -> 2025 Analysis & 1 km Proximity ---

@pytest.mark.asyncio
async def test_mau_forest_demonstration_scenario():
    """Full demonstration scenario:
    1. Select Eastern Mau Forest Reserve AOI.
    2. Run 2020 -> 2025 NDVI change analysis.
    3. Query PostGIS for nearby infrastructure within 1 km (1000 m).
    4. Validate PostGIS ST_DWithin and ST_Distance calculations.
    5. Query an empty radius to confirm zero-result handling.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Fetch AOI
        aoi_res = await ac.get("/api/aois?format=json")
        assert aoi_res.status_code == 200
        aois = aoi_res.json()["aois"]
        mau_aoi = next(a for a in aois if "Mau" in a["name"])
        aoi_id = mau_aoi["id"]

        # 2. Fetch Scenes
        scenes_res = await ac.get(f"/api/aois/{aoi_id}/scenes")
        assert scenes_res.status_code == 200
        scenes = scenes_res.json()["scenes"]
        scene_2020 = next(s for s in scenes if "20200115" in s["scene_identifier"])
        scene_2025 = next(s for s in scenes if "20250120" in s["scene_identifier"])

        # 3. Execute Analysis
        payload = {
            "aoi_id": aoi_id,
            "before_scene_id": scene_2020["id"],
            "after_scene_id": scene_2025["id"],
            "threshold": -0.20,
            "minimum_area_m2": 500.0,
        }
        analysis_res = await ac.post("/api/analysis/ndvi-change", json=payload)
        assert analysis_res.status_code == 200
        analysis_data = analysis_res.json()
        analysis_id = analysis_data["analysis_id"]

        # 4. Query Nearby Infrastructure within 1 km (1000 m)
        proximity_res = await ac.get(f"/api/analysis/{analysis_id}/nearby-infrastructure?radius_m=1000")
        assert proximity_res.status_code == 200
        proximity_data = proximity_res.json()

        assert proximity_data["infrastructure_count"] >= 3
        infra_names = [item["name"] for item in proximity_data["infrastructure"]]
        assert any("Ranger Station" in name or "Access" in name or "Highway" in name for name in infra_names)

        distances = [item["distance_m"] for item in proximity_data["infrastructure"]]
        assert all(d <= 1000.0 for d in distances)
        assert distances == sorted(distances)

        # 5. Query Spatial Summary
        summary_res = await ac.get(f"/api/analysis/{analysis_id}/spatial-summary?radius_m=1000")
        assert summary_res.status_code == 200
        summary_data = summary_res.json()
        assert summary_data["change_metrics"]["total_change_area_ha"] > 100.0
        assert summary_data["aoi_containment"]["all_contained"] is True

        # 6. Test Empty Radius in Harz at 100m
        harz_aoi = next(a for a in aois if "Harz" in a["name"])
        harz_scenes_res = await ac.get(f"/api/aois/{harz_aoi['id']}/scenes")
        harz_scenes = harz_scenes_res.json()["scenes"]
        harz_2019 = next(s for s in harz_scenes if "20190718" in s["scene_identifier"])
        harz_2024 = next(s for s in harz_scenes if "20240722" in s["scene_identifier"])

        harz_analysis_res = await ac.post(
            "/api/analysis/ndvi-change",
            json={
                "aoi_id": harz_aoi["id"],
                "before_scene_id": harz_2019["id"],
                "after_scene_id": harz_2024["id"],
                "threshold": -0.20,
                "minimum_area_m2": 500.0,
            },
        )
        assert harz_analysis_res.status_code == 200
        harz_analysis_id = harz_analysis_res.json()["analysis_id"]

        harz_empty_res = await ac.get(f"/api/analysis/{harz_analysis_id}/nearby-infrastructure?radius_m=100")
        assert harz_empty_res.status_code == 200
        harz_empty_data = harz_empty_res.json()
        assert harz_empty_data["infrastructure_count"] == 0
        assert len(harz_empty_data["infrastructure"]) == 0
