"""TerraLens Phase 4 Comprehensive Agent Orchestrator Test Suite.

Verifies:
1. Valid natural-language request processing.
2. AOI resolution for cataloged study areas.
3. Scene resolution with temporal filtering.
4. Successful NDVI analysis and PostGIS vectorization.
5. Quality Gate validation pass.
6. Quality Gate validation failure handling.
7. Stable/no-change scenario handling (not_actionable).
8. Cloudy imagery rejection (cloud cover > 20%).
9. PostGIS spatial impact retrieval (infrastructure and population).
10. Unrecognized/missing AOI graceful handling.
11. Missing scenes error handling.
12. Downstream GIS failure resilience.
13. Deterministic demo mode when no LLM API key is present.
14. Standardized response schema on POST /api/agent/analyze and GET /api/agent/health.
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.database.session import AsyncSessionLocal
from app.agents.models import AgentAnalyzeRequest, AgentAnalyzeResponse, AgentHealthResponse
from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import tool_registry
from app.agents.llm_client import get_llm_client, MockLLMClient


# --- 1. Valid Natural Language Request ---

@pytest.mark.asyncio
async def test_valid_natural_language_request():
    """Verify standard natural language query resolves and executes complete pipeline."""
    query = "Analyze vegetation change in Eastern Mau Forest between 2020 and 2025 and find nearby infrastructure within 1000m"
    async with AsyncSessionLocal() as db:
        res = await AgentOrchestrator.analyze(
            request=query,
            db=db,
            provider="mock",
        )
        assert res.status == "validated"
        assert res.aoi == "Eastern Mau Forest Reserve"
        assert res.analysis_id is not None
        assert res.change.area_ha > 100.0
        assert res.change.polygon_count > 0
        assert res.spatial_impact.infrastructure_count >= 3
        assert res.validation.passed is True
        assert res.recommended_action == "ISSUE_MONITORING_ALERT"
        assert len(res.evidence) >= 3


# --- 2. AOI Resolution ---

@pytest.mark.asyncio
async def test_aoi_resolution_mau_and_harz():
    """Verify tool layer resolves AOIs correctly by name or keyword."""
    async with AsyncSessionLocal() as db:
        mau_res = await tool_registry.execute(
            name="get_aoi",
            parameters={"name": "Mau Forest"},
            db=db,
        )
        assert mau_res.success is True
        assert "Mau" in mau_res.data["name"]

        harz_res = await tool_registry.execute(
            name="get_aoi",
            parameters={"name": "Harz"},
            db=db,
        )
        assert harz_res.success is True
        assert "Harz" in harz_res.data["name"]


# --- 3. Scene Resolution ---

@pytest.mark.asyncio
async def test_scene_resolution_with_year_filters():
    """Verify tool layer resolves clean before and after scenes for an AOI."""
    async with AsyncSessionLocal() as db:
        # Get Mau AOI ID
        aoi_data = (await tool_registry.execute(name="get_aoi", parameters={"name": "Mau Forest"}, db=db)).data
        aoi_id = uuid.UUID(aoi_data["id"])

        scenes_res = await tool_registry.execute(
            name="list_scenes",
            parameters={"aoi_id": aoi_id, "before_year": 2020, "after_year": 2025},
            db=db,
        )
        assert scenes_res.success is True
        before = scenes_res.data["before_scene"]
        after = scenes_res.data["after_scene"]
        assert "2020" in before["scene_identifier"]
        assert "2025" in after["scene_identifier"]
        assert before["cloud_cover"] <= 20.0
        assert after["cloud_cover"] <= 20.0


# --- 4. Successful NDVI Analysis & Vectorization ---

@pytest.mark.asyncio
async def test_ndvi_analysis_and_vectorization():
    """Verify deterministic NDVI calculation and polygon generation through tool layer."""
    async with AsyncSessionLocal() as db:
        aoi_data = (await tool_registry.execute(name="get_aoi", parameters={"name": "Mau Forest"}, db=db)).data
        aoi_id = uuid.UUID(aoi_data["id"])

        scenes_res = (await tool_registry.execute(name="list_scenes", parameters={"aoi_id": aoi_id, "before_year": 2020, "after_year": 2025}, db=db)).data
        before_id = uuid.UUID(scenes_res["before_scene"]["id"])
        after_id = uuid.UUID(scenes_res["after_scene"]["id"])

        res = await tool_registry.execute(
            name="run_ndvi_analysis",
            parameters={
                "aoi_id": aoi_id,
                "before_scene_id": before_id,
                "after_scene_id": after_id,
                "threshold": -0.20,
            },
            db=db,
        )
        assert res.success is True
        metrics = res.data["metrics"]
        assert metrics["total_change_area_ha"] > 100.0
        assert metrics["change_polygon_count"] >= 1


# --- 5. Quality Gate Pass ---

@pytest.mark.asyncio
async def test_quality_gate_pass():
    """Verify Quality Gate passes on clean Mau 2020 -> 2025 analysis."""
    async with AsyncSessionLocal() as db:
        aoi_data = (await tool_registry.execute(name="get_aoi", parameters={"name": "Mau Forest"}, db=db)).data
        aoi_id = uuid.UUID(aoi_data["id"])

        scenes_res = (await tool_registry.execute(name="list_scenes", parameters={"aoi_id": aoi_id, "before_year": 2020, "after_year": 2025}, db=db)).data
        before_id = uuid.UUID(scenes_res["before_scene"]["id"])
        after_id = uuid.UUID(scenes_res["after_scene"]["id"])

        analysis_res = (await tool_registry.execute(name="run_ndvi_analysis", parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": after_id}, db=db)).data
        analysis_id = uuid.UUID(analysis_res["analysis_id"])

        val_res = await tool_registry.execute(
            name="validate_analysis",
            parameters={
                "aoi_id": aoi_id,
                "before_scene_id": before_id,
                "after_scene_id": after_id,
                "analysis_id": analysis_id,
            },
            db=db,
        )
        assert val_res.success is True
        assert val_res.data["status"] == "PASSED"
        assert val_res.data["passed_checks"] >= 5


# --- 6. Quality Gate Failure (Sub-threshold delta) ---

@pytest.mark.asyncio
async def test_quality_gate_failure_strict_threshold():
    """Verify Quality Gate fails when change delta does not satisfy an impossibly strict threshold."""
    async with AsyncSessionLocal() as db:
        aoi_data = (await tool_registry.execute(name="get_aoi", parameters={"name": "Mau Forest"}, db=db)).data
        aoi_id = uuid.UUID(aoi_data["id"])

        scenes_res = (await tool_registry.execute(name="list_scenes", parameters={"aoi_id": aoi_id, "before_year": 2020, "after_year": 2025}, db=db)).data
        before_id = uuid.UUID(scenes_res["before_scene"]["id"])
        after_id = uuid.UUID(scenes_res["after_scene"]["id"])

        analysis_res = (await tool_registry.execute(name="run_ndvi_analysis", parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": after_id}, db=db)).data
        analysis_id = uuid.UUID(analysis_res["analysis_id"])

        # Pass impossibly strict threshold (-0.99)
        val_res = await tool_registry.execute(
            name="validate_analysis",
            parameters={
                "aoi_id": aoi_id,
                "before_scene_id": before_id,
                "after_scene_id": after_id,
                "analysis_id": analysis_id,
                "threshold": -0.99,
            },
            db=db,
        )
        assert val_res.success is True
        assert val_res.data["status"] == "VALIDATION_FAILED"


# --- 7. Stable / No-Change Scenario ---

@pytest.mark.asyncio
async def test_stable_canopy_no_change_scenario():
    """Verify agent handles baseline-to-stable comparison without false alerts (not_actionable)."""
    async with AsyncSessionLocal() as db:
        q_aoi = await db.execute(text("SELECT id FROM aois WHERE name ILIKE '%Mau%';"))
        aoi_id = q_aoi.scalar_one()

        q_before = await db.execute(text("SELECT id FROM satellite_scenes WHERE aoi_id = :aoi_id AND scene_identifier ILIKE '%20200115%';"), {"aoi_id": aoi_id})
        before_id = q_before.scalar_one()

        q_stable = await db.execute(text("SELECT id FROM satellite_scenes WHERE aoi_id = :aoi_id AND scene_identifier ILIKE '%STABLE%';"), {"aoi_id": aoi_id})
        stable_id = q_stable.scalar_one()

        # Run analysis between 2020 baseline and 2020 stable
        analysis_res = (await tool_registry.execute(
            name="run_ndvi_analysis",
            parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": stable_id},
            db=db,
        )).data
        analysis_id = uuid.UUID(analysis_res["analysis_id"])

        val_res = (await tool_registry.execute(
            name="validate_analysis",
            parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": stable_id, "analysis_id": analysis_id},
            db=db,
        )).data

        # Evaluate decision on state
        from app.agents.models import AgentState, QualityGateReport
        state = AgentState(
            user_request="Check Mau stable canopy",
            selected_aoi={"id": str(aoi_id), "name": "Eastern Mau Forest Reserve"},
            before_scene={"id": str(before_id), "acquisition_date": "2020-01-15"},
            after_scene={"id": str(stable_id), "acquisition_date": "2020-01-20"},
            analysis_id=str(analysis_id),
            validation_result=QualityGateReport(**val_res),
            change_area_ha=0.0,
            polygon_count=0,
        )

        client = get_llm_client("mock")
        status, action, summary, evidence = await client.evaluate_decision(state)

        assert status == "not_actionable"
        assert action == "NO_ACTION_REQUIRED"
        assert "stable" in summary.lower()


# --- 8. Cloudy / Bad Imagery Case ---

@pytest.mark.asyncio
async def test_cloudy_bad_imagery_rejection():
    """Verify Quality Gate rejects high-cloud scenes (>20% cloud cover)."""
    async with AsyncSessionLocal() as db:
        q_aoi = await db.execute(text("SELECT id FROM aois WHERE name ILIKE '%Mau%';"))
        aoi_id = q_aoi.scalar_one()

        q_before = await db.execute(text("SELECT id FROM satellite_scenes WHERE aoi_id = :aoi_id AND scene_identifier ILIKE '%20200115%';"), {"aoi_id": aoi_id})
        before_id = q_before.scalar_one()

        q_cloud = await db.execute(text("SELECT id FROM satellite_scenes WHERE aoi_id = :aoi_id AND scene_identifier ILIKE '%HIGHCLOUD%';"), {"aoi_id": aoi_id})
        cloud_id = q_cloud.scalar_one()

        analysis_res = (await tool_registry.execute(
            name="run_ndvi_analysis",
            parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": cloud_id},
            db=db,
        )).data
        analysis_id = uuid.UUID(analysis_res["analysis_id"])

        val_res = (await tool_registry.execute(
            name="validate_analysis",
            parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": cloud_id, "analysis_id": analysis_id},
            db=db,
        )).data

        assert val_res["status"] == "VALIDATION_FAILED"
        assert "cloud" in val_res["failure_reason"].lower()


# --- 9. Spatial Impact Retrieval ---

@pytest.mark.asyncio
async def test_spatial_impact_infrastructure_and_population():
    """Verify spatial tools retrieve infrastructure proximity and population demographic overlap."""
    async with AsyncSessionLocal() as db:
        aoi_data = (await tool_registry.execute(name="get_aoi", parameters={"name": "Mau Forest"}, db=db)).data
        aoi_id = uuid.UUID(aoi_data["id"])

        scenes_res = (await tool_registry.execute(name="list_scenes", parameters={"aoi_id": aoi_id, "before_year": 2020, "after_year": 2025}, db=db)).data
        before_id = uuid.UUID(scenes_res["before_scene"]["id"])
        after_id = uuid.UUID(scenes_res["after_scene"]["id"])

        analysis_res = (await tool_registry.execute(name="run_ndvi_analysis", parameters={"aoi_id": aoi_id, "before_scene_id": before_id, "after_scene_id": after_id}, db=db)).data
        analysis_id = uuid.UUID(analysis_res["analysis_id"])

        infra_res = await tool_registry.execute(
            name="find_nearby_infrastructure",
            parameters={"analysis_id": analysis_id, "radius_m": 1000.0},
            db=db,
        )
        assert infra_res.success is True
        assert infra_res.data["infrastructure_count"] >= 3

        pop_res = await tool_registry.execute(
            name="get_population_context",
            parameters={"analysis_id": analysis_id, "radius_m": 1000.0},
            db=db,
        )
        assert pop_res.success is True
        assert pop_res.data["intersecting_zones_count"] >= 1
        assert pop_res.data["total_intersecting_population"] > 0


# --- 10. Missing / Unrecognized AOI ---

@pytest.mark.asyncio
async def test_unrecognized_aoi_handling():
    """Verify agent safely rejects unknown geographic locations."""
    async with AsyncSessionLocal() as db:
        res = await AgentOrchestrator.analyze(
            request="Analyze vegetation in Atlantis Underwater Sanctuary from 2020 to 2025",
            db=db,
            provider="mock",
        )
        assert res.status == "rejected"
        assert res.recommended_action == "REJECT_UNRECOGNIZED_AOI"
        assert len(res.evidence) >= 1


# --- 11. Missing Scenes Handling ---

@pytest.mark.asyncio
async def test_missing_scenes_handling():
    """Verify agent gracefully handles requests for non-existent years."""
    async with AsyncSessionLocal() as db:
        # Request for year 1950
        res = await AgentOrchestrator.analyze(
            request="Analyze vegetation in Mau Forest from 1950 to 1955",
            db=db,
            provider="mock",
        )
        # Should gracefully resolve available scenes or reject
        assert res.status in ("validated", "rejected")


# --- 12. Downstream GIS Resilience ---

@pytest.mark.asyncio
async def test_downstream_gis_failure_resilience():
    """Verify tool execution handles invalid scene IDs without crashing orchestrator."""
    async with AsyncSessionLocal() as db:
        fake_aoi_id = uuid.uuid4()
        fake_scene_id = uuid.uuid4()

        res = await tool_registry.execute(
            name="run_ndvi_analysis",
            parameters={
                "aoi_id": fake_aoi_id,
                "before_scene_id": fake_scene_id,
                "after_scene_id": fake_scene_id,
            },
            db=db,
        )
        assert res.success is False
        assert res.error is not None


# --- 13. Deterministic Demo Mode ---

@pytest.mark.asyncio
async def test_deterministic_demo_mode():
    """Verify Agent operates seamlessly in demo mode without any external API keys."""
    async with AsyncSessionLocal() as db:
        res = await AgentOrchestrator.analyze(
            request="Analyze vegetation change in Harz National Park from 2019 to 2024",
            db=db,
            provider="mock",
        )
        assert res.status == "validated"
        assert res.orchestration_mode == "deterministic_demo"
        assert "Harz" in res.aoi
        assert res.change.area_ha > 0.0


# --- 14. Standardized Response Schema on API Endpoints ---

@pytest.mark.asyncio
async def test_api_agent_analyze_and_health_endpoints():
    """Verify POST /api/agent/analyze and GET /api/agent/health adhere to exact schema."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Health check
        health_resp = await ac.get("/api/agent/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "online"
        assert health_data["registered_tools_count"] >= 10
        assert health_data["database_connected"] is True

        # 2. Analyze endpoint
        analyze_resp = await ac.post(
            "/api/agent/analyze",
            json={
                "request": "Analyze vegetation change in Eastern Mau Forest from 2020 to 2025",
            },
        )
        assert analyze_resp.status_code == 200
        data = analyze_resp.json()

        # Check required schema keys
        assert "status" in data
        assert "aoi" in data
        assert "analysis_period" in data
        assert "change" in data
        assert "spatial_impact" in data
        assert "validation" in data
        assert "recommended_action" in data
        assert "evidence" in data

        assert data["status"] == "validated"
        assert data["recommended_action"] == "ISSUE_MONITORING_ALERT"
        assert isinstance(data["evidence"], list)
        assert len(data["evidence"]) >= 3
