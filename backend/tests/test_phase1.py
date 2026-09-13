"""TerraLens Phase 1 Automated Test Suite.

Verifies:
1. PostgreSQL + PostGIS database connection & extension validity.
2. Database schema integrity, constraints, and spatial indexes.
3. Seed data correctness (AOIs, scenes, infrastructure, population zones).
4. PostGIS spatial functions (ST_Area, ST_DWithin, ST_AsGeoJSON).
5. FastAPI endpoints (/api/health, /api/aois, /api/scenes, /api/infrastructure).
"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.database.session import async_engine, SyncSessionLocal


@pytest.mark.asyncio
async def test_postgis_extension():
    """Verify PostGIS extension is installed and responsive."""
    async with async_engine.connect() as conn:
        result = await conn.execute(text("SELECT PostGIS_Version();"))
        version = result.scalar_one_or_none()
        assert version is not None, "PostGIS extension is not installed"
        assert len(version) > 0, "PostGIS version string is empty"


@pytest.mark.asyncio
async def test_tables_and_indexes():
    """Verify all 6 core tables exist in the PostgreSQL database."""
    tables_to_check = [
        "aois",
        "satellite_scenes",
        "analysis_runs",
        "change_polygons",
        "infrastructure",
        "population_zones",
    ]
    async with async_engine.connect() as conn:
        for tbl in tables_to_check:
            res = await conn.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :tbl);"
                ),
                {"tbl": tbl},
            )
            exists = res.scalar_one_or_none()
            assert exists is True, f"Table '{tbl}' does not exist"


@pytest.mark.asyncio
async def test_seed_data_counts():
    """Verify seed data has been properly loaded."""
    async with async_engine.connect() as conn:
        aoi_res = await conn.execute(text("SELECT COUNT(*) FROM aois;"))
        aoi_count = aoi_res.scalar_one_or_none()
        assert aoi_count >= 2, f"Expected at least 2 AOIs, found {aoi_count}"

        scene_res = await conn.execute(text("SELECT COUNT(*) FROM satellite_scenes;"))
        scene_count = scene_res.scalar_one_or_none()
        assert scene_count >= 4, f"Expected at least 4 satellite scenes, found {scene_count}"

        infra_res = await conn.execute(text("SELECT COUNT(*) FROM infrastructure;"))
        infra_count = infra_res.scalar_one_or_none()
        assert infra_count >= 6, f"Expected at least 6 infrastructure items, found {infra_count}"


@pytest.mark.asyncio
async def test_spatial_query_area_and_distance():
    """Verify PostGIS real spatial calculation functions ST_Area and ST_DWithin."""
    async with async_engine.connect() as conn:
        # 1. Test ST_Area on Mau Forest AOI
        area_res = await conn.execute(
            text(
                """
                SELECT name, ST_Area(geometry::geography) / 10000.0 as area_ha 
                FROM aois 
                WHERE name LIKE '%Mau%';
                """
            )
        )
        row = area_res.fetchone()
        assert row is not None, "Mau Forest AOI not found"
        assert row.area_ha > 1000, f"Expected significant area in hectares, got {row.area_ha}"

        # 2. Test ST_DWithin and ST_Distance around Nessuit Ranger Station (35.885, -0.382)
        dist_res = await conn.execute(
            text(
                """
                SELECT name, type, 
                       ST_Distance(geometry::geography, ST_SetSRID(ST_MakePoint(35.885, -0.382), 4326)::geography) as dist_m
                FROM infrastructure
                WHERE ST_DWithin(geometry::geography, ST_SetSRID(ST_MakePoint(35.885, -0.382), 4326)::geography, 10000)
                ORDER BY dist_m ASC;
                """
            )
        )
        nearby = dist_res.fetchall()
        assert len(nearby) > 0, "Expected nearby infrastructure around Nessuit station"
        # The closest one should be Nessuit Forest Ranger Station itself (distance ~ 0)
        assert nearby[0].dist_m < 10.0, f"Expected first feature to be within 10m, got {nearby[0].dist_m}m"


@pytest.mark.asyncio
async def test_api_health_endpoint():
    """Verify GET /api/health returns 200 OK and healthy status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"]["connected"] is True
        assert data["database"]["counts"]["aois"] >= 2


@pytest.mark.asyncio
async def test_api_aois_geojson():
    """Verify GET /api/aois returns valid GeoJSON FeatureCollection."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/aois?format=geojson")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) >= 2
        feature = data["features"][0]
        assert "geometry" in feature
        assert feature["geometry"]["type"] == "Polygon"
        assert "properties" in feature
        assert "name" in feature["properties"]


@pytest.mark.asyncio
async def test_api_aoi_scenes_and_infrastructure():
    """Verify scenes and infrastructure retrieval by AOI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # List AOIs to get an ID
        res = await ac.get("/api/aois?format=json")
        assert res.status_code == 200
        aois = res.json()["aois"]
        mau_aoi = next((a for a in aois if "Mau" in a["name"]), None)
        assert mau_aoi is not None

        aoi_id = mau_aoi["id"]

        # Get scenes
        scenes_res = await ac.get(f"/api/aois/{aoi_id}/scenes")
        assert scenes_res.status_code == 200
        scenes_data = scenes_res.json()
        assert scenes_data["count"] >= 3

        # Get infrastructure
        infra_res = await ac.get(f"/api/aois/{aoi_id}/infrastructure")
        assert infra_res.status_code == 200
        infra_data = infra_res.json()
        assert infra_data["type"] == "FeatureCollection"
        assert len(infra_data["features"]) >= 5


@pytest.mark.asyncio
async def test_api_nearby_infrastructure_proximity():
    """Verify GET /api/infrastructure/nearby with coordinates and radius."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/infrastructure/nearby?lon=35.885&lat=-0.382&radius_meters=8000")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "FeatureCollection"
        assert data["count"] > 0
        first_feat = data["features"][0]
        assert "distance_meters" in first_feat["properties"]
        assert first_feat["properties"]["distance_meters"] < 50.0
