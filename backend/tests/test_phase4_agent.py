"""TerraLens Phase 4 Automated Test Suite - AI Tool-Calling Agent & Quality Gate.

Verifies:
1. Tool registration in ToolRegistry.
2. Unknown tool rejection (security enforcement).
3. Parameter validation before execution.
4. MockLLMClient and AgentPlanner plan generation.
5. Natural language query resolution for Mau Forest 2020 -> 2025.
6. Variable resolution ($aoi_id, $before_scene_id, $analysis_id).
7. Full end-to-end agent query execution with verified explanation.
8. Quality Gate multi-check evaluation report.
9. High-cloud scene rejection (Cloud cover > 20% limit).
10. Stable/no-change scenario handling.
11. PostGIS AOI containment verification within Quality Gate.
12. FastAPI POST /api/agent/query endpoint.
13. FastAPI POST /api/agent/plan endpoint.
14. FastAPI GET /api/agent/tools endpoint.
15. Error handling for malformed or empty queries.
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.database.session import AsyncSessionLocal
from app.agents.models import AnalysisPlan, PlanStep
from app.agents.tools import tool_registry
from app.agents.planner import AgentPlanner
from app.agents.orchestrator import AgentOrchestrator
from app.agents.llm_client import MockLLMClient, get_llm_client
from app.validation.quality_gate import QualityGate
from app.gis.validation import GISValidationError


# --- 1. Tool Registration in ToolRegistry ---

def test_tool_registration():
    """Verify all allowlisted tools are registered in ToolRegistry."""
    catalog = tool_registry.get_catalog()
    assert len(catalog) >= 7
    registered_names = [t["name"] for t in catalog]

    expected_tools = [
        "get_aoi",
        "get_satellite_metadata",
        "run_ndvi_change_pipeline",
        "validate_analysis",
        "calculate_change_area",
        "find_nearby_infrastructure",
        "analyze_population_proximity",
        "run_spatial_intersection",
    ]
    for tool_name in expected_tools:
        assert tool_name in registered_names, f"Tool '{tool_name}' must be registered"
        assert tool_registry.is_registered(tool_name) is True


# --- 2. Unknown Tool Rejection ---

@pytest.mark.asyncio
async def test_unknown_tool_rejection():
    """Verify ToolRegistry rejects unallowlisted tools without executing arbitrary code."""
    async with AsyncSessionLocal() as db:
        res = await tool_registry.execute(
            name="execute_arbitrary_sql",
            parameters={"query": "DROP TABLE aois;"},
            db=db,
        )
        assert res.success is False
        assert "not in allowlisted registry" in res.summary
        assert res.error is not None


# --- 3. Parameter Validation ---

@pytest.mark.asyncio
async def test_tool_parameter_validation():
    """Verify ToolRegistry validates parameter types against Pydantic schema before execution."""
    async with AsyncSessionLocal() as db:
        # Pass invalid negative radius to find_nearby_infrastructure
        res = await tool_registry.execute(
            name="find_nearby_infrastructure",
            parameters={"analysis_id": str(uuid.uuid4()), "radius_m": -100.0},
            db=db,
        )
        assert res.success is False
        assert "Invalid parameters" in res.summary


# --- 4. Mock Planner Plan Generation ---

@pytest.mark.asyncio
async def test_mock_planner_plan_generation():
    """Verify AgentPlanner produces a valid AnalysisPlan with correct allowlisted steps."""
    query = "Find significant vegetation loss in the Mau Forest between 2020 and 2025 and show infrastructure within 1 km."
    plan = await AgentPlanner.create_plan(query=query)

    assert isinstance(plan, AnalysisPlan)
    assert plan.aoi_name == "Eastern Mau Forest Reserve"
    assert plan.timeframe["before_year"] == 2020
    assert plan.timeframe["after_year"] == 2025
    assert plan.parameters["proximity_radius_m"] == 1000.0
    assert plan.parameters["threshold"] == -0.20
    assert len(plan.steps) >= 5

    step_tools = [s.tool for s in plan.steps]
    assert "get_aoi" in step_tools
    assert "get_satellite_metadata" in step_tools
    assert "run_ndvi_change_pipeline" in step_tools
    assert "validate_analysis" in step_tools
    assert "find_nearby_infrastructure" in step_tools


# --- 5. Natural Language Query Resolution ---

@pytest.mark.asyncio
async def test_query_resolution_harz():
    """Verify planner parses Harz National Park query with customized timeframe and radius."""
    query = "Analyze bark beetle dieback in Harz National Park from 2019 to 2024 and find infrastructure within 500 m"
    plan = await AgentPlanner.create_plan(query=query)

    assert "Harz" in plan.aoi_name
    assert plan.timeframe["before_year"] == 2019
    assert plan.timeframe["after_year"] == 2024
    assert plan.parameters["proximity_radius_m"] == 500.0


# --- 6. Variable Resolution in Orchestrator ---

def test_variable_resolution():
    """Verify recursive substitution of $variables in parameter dictionaries."""
    variables = {
        "aoi_id": uuid.UUID("a0000000-0000-0000-0000-000000000001"),
        "before_scene_id": uuid.UUID("b0000000-0000-0000-0000-000000000001"),
        "analysis_id": uuid.UUID("77caba3d-0c7e-43dc-96c9-bdd371cb1f0d"),
    }

    params = {
        "aoi_id": "$aoi_id",
        "before_scene_id": "$before_scene_id",
        "threshold": -0.20,
        "nested": {
            "target": "$analysis_id",
            "static": 100,
        },
    }

    resolved = AgentOrchestrator._resolve_variables(params, variables)
    assert resolved["aoi_id"] == variables["aoi_id"]
    assert resolved["before_scene_id"] == variables["before_scene_id"]
    assert resolved["threshold"] == -0.20
    assert resolved["nested"]["target"] == variables["analysis_id"]
    assert resolved["nested"]["static"] == 100


# --- 7. Full End-to-End Agent Query Execution ---

@pytest.mark.asyncio
async def test_agent_end_to_end_mau_query():
    """Verify complete end-to-end workflow on the Mau Forest 2020 -> 2025 demonstration scenario."""
    query = "Find significant vegetation loss in the Mau Forest between 2020 and 2025 and show infrastructure within 1 km."
    async with AsyncSessionLocal() as db:
        response = await AgentOrchestrator.execute_query(query=query, db=db, provider="mock")

        assert response.status == "COMPLETED"
        assert response.analysis_id is not None
        assert response.aoi is not None
        assert "Mau" in response.aoi["name"]

        # Metrics must come from deterministic tool outputs
        assert response.metrics is not None
        assert response.metrics["total_change_area_ha"] > 100.0
        assert response.metrics["change_polygon_count"] > 0

        # Infrastructure results from PostGIS
        assert response.nearby_infrastructure is not None
        assert len(response.nearby_infrastructure) >= 3
        infra_names = [i["name"] for i in response.nearby_infrastructure]
        assert any("Ranger Station" in name for name in infra_names)

        # Quality Gate report
        assert response.quality_report.status == "PASSED"

        # Activity Log
        assert len(response.activity_log) >= 5
        tools_in_log = [item.tool for item in response.activity_log if item.tool]
        assert "get_aoi" in tools_in_log
        assert "run_ndvi_change_pipeline" in tools_in_log
        assert "find_nearby_infrastructure" in tools_in_log

        # Verified Explanation (strictly non-causal & citing verified numbers)
        assert str(round(response.metrics["total_change_area_ha"], 2)) in response.explanation
        assert "hectares" in response.explanation
        assert "PostGIS" in response.explanation


# --- 8. Quality Gate Multi-Check Evaluation ---

@pytest.mark.asyncio
async def test_quality_gate_evaluation():
    """Verify QualityGate evaluates all gates on an existing valid analysis."""
    async with AsyncSessionLocal() as db:
        report = await QualityGate.evaluate(
            db=db,
            aoi_id=uuid.UUID("a0000000-0000-0000-0000-000000000001"),
            before_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000001"),
            after_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000002"),
            max_cloud_cover=20.0,
            threshold=-0.20,
            min_area_m2=500.0,
        )

        assert report.status == "PASSED"
        assert report.failed_checks == 0
        gate_names = [g.gate_name for g in report.gate_checks]
        assert "AOI_EXISTENCE_GATE" in gate_names
        assert "SCENE_AOI_ALIGNMENT_GATE" in gate_names
        assert "CLOUD_COVER_GATE" in gate_names


# --- 9. High-Cloud Scene Rejection ---

@pytest.mark.asyncio
async def test_quality_gate_high_cloud_rejection():
    """Verify Quality Gate rejects high-cloud scene (> 20% cloud cover)."""
    async with AsyncSessionLocal() as db:
        # b0000000-0000-0000-0000-000000000003 is the seeded HIGHCLOUD scene (45.5% cloud)
        report = await QualityGate.evaluate(
            db=db,
            aoi_id=uuid.UUID("a0000000-0000-0000-0000-000000000001"),
            before_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000001"),
            after_scene_id=uuid.UUID("b0000000-0000-0000-0000-000000000003"),
            max_cloud_cover=20.0,
        )

        assert report.status == "VALIDATION_FAILED"
        assert report.failed_checks > 0
        assert "Cloud cover exceeded limit" in (report.failure_reason or "")


# --- 10. Stable / No-Change Scenario ---

@pytest.mark.asyncio
async def test_stable_scene_agent_explanation():
    """Verify stable comparison produces clean explanation without fabricated change."""
    async with AsyncSessionLocal() as db:
        # Run comparison between 2020 baseline and 2020 stable scene
        res = await tool_registry.execute(
            name="run_ndvi_change_pipeline",
            parameters={
                "aoi_id": uuid.UUID("a0000000-0000-0000-0000-000000000001"),
                "before_scene_id": uuid.UUID("b0000000-0000-0000-0000-000000000001"),
                "after_scene_id": uuid.UUID("b0000000-0000-0000-0000-000000000004"),
                "threshold": -0.20,
                "minimum_area_m2": 500.0,
            },
            db=db,
        )
        assert res.success is True
        data = res.data
        assert data["metrics"]["change_polygon_count"] == 0

        # Synthesize explanation
        client = MockLLMClient()
        plan = AnalysisPlan(
            query="Check stability in Mau Forest in 2020",
            aoi_name="Eastern Mau Forest Reserve",
            timeframe={"before_year": 2020, "after_year": 2020},
            parameters={"threshold": -0.20},
            steps=[],
        )
        explanation = await client.synthesize_explanation(
            query="Check stability in Mau Forest in 2020",
            plan=plan,
            results={"get_aoi": {"name": "Eastern Mau Forest Reserve"}, "run_ndvi_change_pipeline": data},
        )
        assert "stable" in explanation.lower()
        assert "0 significant vegetation decrease polygons" in explanation


# --- 11. AOI Containment Gate ---

@pytest.mark.asyncio
async def test_quality_gate_aoi_containment():
    """Verify QualityGate AOI_CONTAINMENT_GATE passes for legitimate change polygons."""
    async with AsyncSessionLocal() as db:
        # Get latest analysis run
        q = text("SELECT id, aoi_id, before_scene_id, after_scene_id FROM analysis_runs ORDER BY created_at DESC LIMIT 1;")
        row = (await db.execute(q)).fetchone()
        if row:
            report = await QualityGate.evaluate(
                db=db,
                aoi_id=row.aoi_id,
                before_scene_id=row.before_scene_id,
                after_scene_id=row.after_scene_id,
                analysis_id=row.id,
            )
            assert report.status == "PASSED"
            containment_check = next((c for c in report.gate_checks if c.gate_name == "AOI_CONTAINMENT_GATE"), None)
            assert containment_check is not None
            assert containment_check.status == "PASSED"


# --- 12. API POST /api/agent/query ---

@pytest.mark.asyncio
async def test_api_agent_query_endpoint():
    """Verify FastAPI endpoint POST /api/agent/query."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "query": "Find significant vegetation loss in the Mau Forest between 2020 and 2025 and show infrastructure within 1 km.",
            "llm_provider": "mock",
        }
        res = await ac.post("/api/agent/query", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "COMPLETED"
        assert "analysis_id" in data
        assert "plan" in data
        assert "metrics" in data
        assert "nearby_infrastructure" in data
        assert "quality_report" in data
        assert "activity_log" in data
        assert "explanation" in data


# --- 13. API POST /api/agent/plan ---

@pytest.mark.asyncio
async def test_api_agent_plan_endpoint():
    """Verify FastAPI endpoint POST /api/agent/plan generates plan without executing tools."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "query": "Detect vegetation change in Harz National Park between 2019 and 2024 and find nearby assets within 2 km"
        }
        res = await ac.post("/api/agent/plan", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert "steps" in data
        assert len(data["steps"]) >= 5
        assert "Harz" in data["aoi_name"]
        assert data["timeframe"]["before_year"] == 2019
        assert data["timeframe"]["after_year"] == 2024


# --- 14. API GET /api/agent/tools ---

@pytest.mark.asyncio
async def test_api_agent_tools_endpoint():
    """Verify FastAPI endpoint GET /api/agent/tools returns allowlisted tool catalog."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/agent/tools")
        assert res.status_code == 200
        data = res.json()

        assert "count" in data
        assert "tools" in data
        assert data["count"] >= 7
        tool_names = [t["name"] for t in data["tools"]]
        assert "get_aoi" in tool_names
        assert "find_nearby_infrastructure" in tool_names


# --- 15. Malformed & Empty Query Error Handling ---

@pytest.mark.asyncio
async def test_api_agent_error_handling_short_query():
    """Verify API returns 422 Unprocessable Entity on empty or short queries."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/agent/query", json={"query": "a"})
        assert res.status_code == 422

        res2 = await ac.post("/api/agent/plan", json={"query": ""})
        assert res2.status_code == 422


# --- 16. Regression Test: Numerical Consistency with Phase 2/3 GIS Engine ---

@pytest.mark.asyncio
async def test_agent_numerical_consistency_with_phase2_3():
    """Verify that agent orchestration produces 100% numerically identical results
    to direct Phase 2 GIS pipeline and Phase 3 PostGIS spatial service calls.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Direct Phase 2 & 3 GIS Execution
        aoi_res = await ac.get("/api/aois?format=json")
        mau_aoi = next(a for a in aoi_res.json()["aois"] if "Mau" in a["name"])
        aoi_id = mau_aoi["id"]

        scenes_res = await ac.get(f"/api/aois/{aoi_id}/scenes")
        scenes = scenes_res.json()["scenes"]
        scene_2020 = next(s for s in scenes if "20200115" in s["scene_identifier"])
        scene_2025 = next(s for s in scenes if "20250120" in s["scene_identifier"])

        direct_gis_res = await ac.post(
            "/api/analysis/ndvi-change",
            json={
                "aoi_id": aoi_id,
                "before_scene_id": scene_2020["id"],
                "after_scene_id": scene_2025["id"],
                "threshold": -0.20,
                "minimum_area_m2": 500.0,
            },
        )
        assert direct_gis_res.status_code == 200
        direct_metrics = direct_gis_res.json()["metrics"]
        direct_analysis_id = direct_gis_res.json()["analysis_id"]

        direct_infra_res = await ac.get(f"/api/analysis/{direct_analysis_id}/nearby-infrastructure?radius_m=1000")
        assert direct_infra_res.status_code == 200
        direct_infra_count = direct_infra_res.json()["infrastructure_count"]

        # 2. Agent Orchestration Execution
        agent_res = await ac.post(
            "/api/agent/query",
            json={
                "query": "Find significant vegetation loss in the Mau Forest between 2020 and 2025 and show infrastructure within 1 km."
            },
        )
        assert agent_res.status_code == 200
        agent_data = agent_res.json()
        agent_metrics = agent_data["metrics"]

        # 3. Assert Exact Numerical Equivalence
        assert agent_metrics["total_change_area_ha"] == direct_metrics["total_change_area_ha"] == 881.8391
        assert agent_metrics["total_change_area_m2"] == direct_metrics["total_change_area_m2"] == 8818390.74
        assert agent_metrics["changed_pixels_count"] == direct_metrics["changed_pixels_count"] == 5511
        assert agent_metrics["change_polygon_count"] == direct_metrics["change_polygon_count"] == 3
        assert agent_metrics["mean_before_ndvi"] == direct_metrics["mean_before_ndvi"] == 0.7762
        assert agent_metrics["mean_after_ndvi"] == direct_metrics["mean_after_ndvi"] == 0.7516
        assert agent_metrics["mean_ndvi_difference"] == direct_metrics["mean_ndvi_difference"] == -0.0246
        assert len(agent_data["nearby_infrastructure"]) == direct_infra_count == 5

        # 4. Verify Quality Gate Radiometric Report distinguishes polygon vs scene delta
        radiometric_gate = next(
            g for g in agent_data["quality_report"]["gate_checks"] if g["gate_name"] == "RADIOMETRIC_DELTA_GATE"
        )
        assert radiometric_gate["status"] == "PASSED"
        assert radiometric_gate["value"]["polygon_count"] == 3
        assert radiometric_gate["value"]["mean_polygon_ndvi_change"] == -0.7307
        assert round(radiometric_gate["value"]["global_mean_ndvi_difference"], 3) == -0.025
        assert radiometric_gate["value"]["mean_polygon_ndvi_change"] <= -0.20
