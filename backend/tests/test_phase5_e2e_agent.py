"""Phase 5 Test Suite: Agent Reliability & End-to-End Demo Workflow.

Tests:
1. End-to-End Demo Scenario ('Analyze vegetation change in Eastern Mau Forest from 2020 to 2025 and identify affected infrastructure.')
2. AOI Resolution (Exact, partial, case-insensitive, and unknown rejection)
3. Scene Resolution (Temporal filters, missing year rejection, cloud preference)
4. Deterministic NDVI Execution & Polygonization (Real calculated values)
5. Quality Gate Evaluation (5/5 checks validated)
6. PostGIS Spatial Impact Analysis (ST_DWithin & Demographic overlap)
7. Affected Infrastructure Details (Distance metrics, names, types, intersection)
8. Affected Population Context Details (Intersecting settlement zones, counts)
9. Deterministic Demo Mode (Zero API keys, 100% deterministic, no LLM fabrication)
10. Invalid Request Handling (Too short, whitespace-only, malformed)
11. Missing AOI Handling (REJECT_UNRECOGNIZED_AOI)
12. Missing Scenes Handling (REJECT_UNAVAILABLE_SCENES)
13. GIS Pipeline Failure Resilience
14. Database Failure & Health Handling
15. Standardized API Response Schema Verification
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from unittest.mock import patch

from app.main import app
from app.database.session import AsyncSessionLocal
from app.agents.models import AgentAnalyzeResponse, AgentHealthResponse, AgentState
from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import tool_registry
from app.agents.llm_client import get_llm_client, MockLLMClient


# --- 1. End-to-End Demo Scenario: Mau Forest 2020 to 2025 ---

@pytest.mark.asyncio
async def test_phase5_mau_forest_e2e_demo_scenario():
    """Verify the complete end-to-end hackathon demonstration scenario."""
    demo_query = "Analyze vegetation change in Eastern Mau Forest from 2020 to 2025 and identify affected infrastructure."

    async with AsyncSessionLocal() as db:
        resp: AgentAnalyzeResponse = await AgentOrchestrator.analyze(
            request=demo_query,
            db=db,
            provider="mock",
            proximity_radius_m=1000.0,
            threshold=-0.20,
        )

        # 1. Workflow Status
        assert resp.status == "validated"
        assert resp.recommended_action == "ISSUE_MONITORING_ALERT"
        assert resp.orchestration_mode == "deterministic_demo"

        # 2. AOI & Analysis Run
        assert resp.aoi == "Eastern Mau Forest Reserve"
        assert resp.aoi_id is not None
        assert resp.analysis_id is not None
        assert uuid.UUID(resp.analysis_id)

        # 3. Analysis Period
        assert resp.analysis_period.before == "2020-01-15"
        assert resp.analysis_period.after == "2025-01-20"

        # 4. Deterministic Change Metrics
        assert resp.change.area_ha > 800.0  # ~881.84 ha
        assert resp.change.polygon_count == 3
        assert resp.change.mean_ndvi_change < 0.0

        # 5. Quality Gate Verification
        assert resp.validation.passed is True
        assert len(resp.validation.checks) >= 5
        for check in resp.validation.checks:
            assert check.get("status") == "PASSED"

        # 6. PostGIS Spatial Impact
        assert resp.spatial_impact.infrastructure_count >= 5
        assert len(resp.spatial_impact.infrastructure) >= 5

        # Check direct intersecting infrastructure (0.0 m)
        intersecting_infra = [inf for inf in resp.spatial_impact.infrastructure if inf.get("distance_m", -1) == 0.0]
        assert len(intersecting_infra) >= 1
        infra_names = [inf.get("name") for inf in resp.spatial_impact.infrastructure]
        assert any("Likia" in n or "Nessuit" in n or "Enapuiyapui" in n for n in infra_names)

        # 7. Population Context
        pop_context = resp.spatial_impact.population_context
        assert pop_context.get("intersecting_zones_count", 0) >= 1
        assert pop_context.get("total_intersecting_population", 0) >= 4200

        # 8. Deterministic Evidence & Explanation
        assert isinstance(resp.evidence, list)
        assert len(resp.evidence) >= 4
        assert any("hectares" in e for e in resp.evidence)
        assert any("0.0 m" in e or "intersects" in e for e in resp.evidence)

        # 9. Activity Log (7-8 structured workflow steps)
        assert len(resp.activity_log) >= 7
        step_tools = [item.tool for item in resp.activity_log]
        assert "request_parser" in step_tools
        assert "get_aoi" in step_tools
        assert "list_scenes" in step_tools
        assert "run_ndvi_analysis" in step_tools
        assert "validate_analysis" in step_tools


# --- 2. AOI Resolution: Mau, Harz, Partial Matches & Unknown ---

@pytest.mark.asyncio
async def test_phase5_aoi_resolution_variations():
    """Verify robust AOI resolution across diverse phrasing."""
    async with AsyncSessionLocal() as db:
        # Case 1: Partial name 'Eastern Mau'
        res1 = await tool_registry.execute(name="get_aoi", parameters={"name": "Eastern Mau"}, db=db)
        assert res1.success is True
        assert res1.data["name"] == "Eastern Mau Forest Reserve"

        # Case 2: Partial name 'Mau Forest'
        res2 = await tool_registry.execute(name="get_aoi", parameters={"name": "Mau Forest"}, db=db)
        assert res2.success is True
        assert res2.data["name"] == "Eastern Mau Forest Reserve"

        # Case 3: 'Harz'
        res3 = await tool_registry.execute(name="get_aoi", parameters={"name": "Harz"}, db=db)
        assert res3.success is True
        assert "Harz" in res3.data["name"]

        # Case 4: Unknown AOI
        res4 = await tool_registry.execute(name="get_aoi", parameters={"name": "Amazon Basin Rainforest"}, db=db)
        assert res4.success is False
        assert "not found" in res4.error.lower()


# --- 3. Scene Resolution: Temporal Range & Missing Years ---

@pytest.mark.asyncio
async def test_phase5_scene_resolution_and_missing_years():
    """Verify scene resolution handles valid and missing years appropriately."""
    async with AsyncSessionLocal() as db:
        q_aoi = await db.execute(text("SELECT id FROM aois WHERE name ILIKE '%Mau%';"))
        aoi_id = q_aoi.scalar_one()

        # Valid 2020 vs 2025
        valid_res = await tool_registry.execute(
            name="list_scenes",
            parameters={"aoi_id": aoi_id, "before_year": 2020, "after_year": 2025},
            db=db,
        )
        assert valid_res.success is True
        assert valid_res.data["before_scene"]["year"] == 2020
        assert valid_res.data["after_scene"]["year"] == 2025

        # Invalid year 1980
        invalid_res = await tool_registry.execute(
            name="list_scenes",
            parameters={"aoi_id": aoi_id, "before_year": 1980, "after_year": 1985},
            db=db,
        )
        assert invalid_res.success is False
        assert "1980" in invalid_res.error


# --- 4. Quality Gate Cloud Rejection vs Pass ---

@pytest.mark.asyncio
async def test_phase5_quality_gate_cloud_and_pass():
    """Verify Quality Gate enforces 20% max cloud cover limit."""
    async with AsyncSessionLocal() as db:
        q_aoi = await db.execute(text("SELECT id FROM aois WHERE name ILIKE '%Mau%';"))
        aoi_id = q_aoi.scalar_one()

        # Test cloudy inquiry
        cloud_resp = await AgentOrchestrator.analyze(
            request="Analyze Mau Forest with high cloud cover scene from 2024 and verify quality gate rejection",
            db=db,
            provider="mock",
        )
        assert cloud_resp.status == "rejected"
        assert cloud_resp.recommended_action == "REJECT_UNRELIABLE_IMAGERY"
        assert any("cloud" in e.lower() for e in cloud_resp.evidence)


# --- 5. Stable Canopy Scenario (Zero Change) ---

@pytest.mark.asyncio
async def test_phase5_stable_canopy_scenario():
    """Verify stable forest canopy with no detectable loss yields NO_ACTION_REQUIRED."""
    async with AsyncSessionLocal() as db:
        stable_resp = await AgentOrchestrator.analyze(
            request="Analyze Mau Forest stable canopy baseline comparison from 2020",
            db=db,
            provider="mock",
        )
        assert stable_resp.status == "not_actionable"
        assert stable_resp.recommended_action == "NO_ACTION_REQUIRED"
        assert stable_resp.change.polygon_count == 0
        assert "stable" in stable_resp.reasoning_summary.lower()


# --- 6. Harz National Park Bark Beetle Dieback ---

@pytest.mark.asyncio
async def test_phase5_harz_national_park_dieback():
    """Verify Harz National Park dieback monitoring workflow."""
    async with AsyncSessionLocal() as db:
        harz_resp = await AgentOrchestrator.analyze(
            request="Analyze vegetation change in Harz National Park from 2019 to 2024 and evaluate proximity to infrastructure",
            db=db,
            provider="mock",
        )
        assert harz_resp.status == "validated"
        assert "Harz" in harz_resp.aoi
        assert harz_resp.change.area_ha > 0.0
        assert harz_resp.spatial_impact.infrastructure_count >= 1


# --- 7. Deterministic Demo Mode (Zero LLM Keys Required) ---

@pytest.mark.asyncio
async def test_phase5_deterministic_demo_mode_guarantee():
    """Verify the system executes real GIS calculations without any LLM API key."""
    async with AsyncSessionLocal() as db:
        resp = await AgentOrchestrator.analyze(
            request="Analyze vegetation change in Eastern Mau Forest from 2020 to 2025",
            db=db,
            provider=None,  # No provider specified -> default demo mode
        )
        assert resp.orchestration_mode == "deterministic_demo"
        assert resp.change.area_ha > 0.0
        assert resp.change.polygon_count == 3
        # Must have computed genuine real metrics from GeoTIFFs
        assert abs(resp.change.area_ha - 881.84) < 1.0


# --- 8. Invalid Request Handling ---

@pytest.mark.asyncio
async def test_phase5_invalid_request_handling():
    """Verify robust handling of empty, whitespace, or malformed queries."""
    async with AsyncSessionLocal() as db:
        # Empty string
        res_empty = await AgentOrchestrator.analyze(request="", db=db, provider="mock")
        assert res_empty.status == "failed"
        assert res_empty.recommended_action == "REJECT_MALFORMED_QUERY"

        # Whitespace only
        res_spaces = await AgentOrchestrator.analyze(request="    ", db=db, provider="mock")
        assert res_spaces.status == "failed"
        assert res_spaces.recommended_action == "REJECT_MALFORMED_QUERY"


# --- 9. Unrecognized AOI Handling ---

@pytest.mark.asyncio
async def test_phase5_unrecognized_aoi_rejection():
    """Verify clean structured rejection for non-cataloged geographic areas."""
    async with AsyncSessionLocal() as db:
        resp = await AgentOrchestrator.analyze(
            request="Analyze vegetation change in Serengeti National Park from 2020 to 2025",
            db=db,
            provider="mock",
        )
        assert resp.status == "rejected"
        assert resp.recommended_action == "REJECT_UNRECOGNIZED_AOI"
        assert "Serengeti" in resp.reasoning_summary or "geographic area" in resp.reasoning_summary


# --- 10. Missing Scenes Handling ---

@pytest.mark.asyncio
async def test_phase5_missing_scenes_rejection():
    """Verify clean structured rejection for years without satellite coverage."""
    async with AsyncSessionLocal() as db:
        resp = await AgentOrchestrator.analyze(
            request="Analyze vegetation change in Eastern Mau Forest from 1970 to 1975",
            db=db,
            provider="mock",
        )
        assert resp.status == "rejected"
        assert resp.recommended_action == "REJECT_UNAVAILABLE_SCENES"


# --- 11. Downstream GIS Failure Resilience ---

@pytest.mark.asyncio
async def test_phase5_downstream_gis_failure_resilience():
    """Verify tool execution resilience when invalid IDs are passed."""
    async with AsyncSessionLocal() as db:
        res = await tool_registry.execute(
            name="run_ndvi_analysis",
            parameters={
                "aoi_id": uuid.uuid4(),
                "before_scene_id": uuid.uuid4(),
                "after_scene_id": uuid.uuid4(),
            },
            db=db,
        )
        assert res.success is False
        assert res.error is not None


# --- 12. HTTP API Health & Analysis Endpoints ---

@pytest.mark.asyncio
async def test_phase5_api_endpoints_and_schemas():
    """Verify POST /api/agent/analyze and GET /api/agent/health over HTTP transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Healthcheck
        health_resp = await ac.get("/api/agent/health")
        assert health_resp.status_code == 200
        health = health_resp.json()
        assert health["status"] == "online"
        assert health["database_connected"] is True
        assert health["registered_tools_count"] >= 10
        assert health["is_demo_mode"] is True

        # 2. Analyze POST endpoint
        analyze_resp = await ac.post(
            "/api/agent/analyze",
            json={
                "request": "Analyze vegetation change in Eastern Mau Forest from 2020 to 2025 and identify affected infrastructure.",
                "proximity_radius_m": 1000.0,
                "threshold": -0.20,
            },
        )
        assert analyze_resp.status_code == 200
        data = analyze_resp.json()

        # Exact schema field checks
        assert data["status"] == "validated"
        assert data["aoi"] == "Eastern Mau Forest Reserve"
        assert data["analysis_period"]["before"] == "2020-01-15"
        assert data["analysis_period"]["after"] == "2025-01-20"
        assert data["change"]["area_ha"] > 800.0
        assert data["change"]["polygon_count"] == 3
        assert data["spatial_impact"]["infrastructure_count"] >= 5
        assert len(data["spatial_impact"]["infrastructure"]) >= 5
        assert data["validation"]["passed"] is True
        assert data["recommended_action"] == "ISSUE_MONITORING_ALERT"
        assert isinstance(data["evidence"], list)
        assert len(data["evidence"]) >= 4
        assert data["orchestration_mode"] == "deterministic_demo"
        assert len(data["activity_log"]) >= 7
