"""TerraLens Agent Execution Orchestrator.

Coordinates end-to-end controlled agentic workflow:
1. REQUEST: Ingest natural language query and initialize typed AgentState
2. IDENTIFY AOI: Resolve official Area of Interest boundary and metadata
3. IDENTIFY SCENES: Query and filter Sentinel-2 baseline and comparison scenes
4. RUN ANALYSIS: Compute deterministic NDVI change and PostGIS vectorization
5. VALIDATE: Execute Quality Gate (Cloud Cover, Radiometric Delta, Noise, AOI Containment)
6. SPATIAL IMPACT: Execute PostGIS ST_DWithin and demographic overlap queries
7. DECISION: Formulate objective, non-causal decision and recommended actions
8. RESPONSE: Return structured AgentAnalyzeResponse with deterministic evidence
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    AnalysisPlan,
    AnalysisPeriod,
    ChangeMetricsSummary,
    SpatialImpactSummary,
    ValidationSummary,
    AgentResponse,
    AgentActivityLogItem,
    AgentState,
    AgentAnalyzeResponse,
    QualityGateReport,
    ToolResult,
)
from app.agents.planner import AgentPlanner
from app.agents.tools import tool_registry
from app.agents.llm_client import get_llm_client
from app.config import settings

logger = logging.getLogger("terralens.agents.orchestrator")


class AgentOrchestrator:
    """Executes structured geospatial analysis plans using allowlisted GIS/PostGIS tools."""

    @classmethod
    async def analyze(
        cls,
        request: str,
        db: AsyncSession,
        provider: Optional[str] = None,
        proximity_radius_m: float = 1000.0,
        threshold: float = -0.20,
    ) -> AgentAnalyzeResponse:
        """Execute Phase 4 Controlled Agent Workflow from natural language request."""
        client = get_llm_client(provider=provider)
        is_demo = getattr(client, "api_key", None) == "" or client.__class__.__name__ == "MockLLMClient"
        orch_mode = "deterministic_demo" if is_demo else "llm"

        state = AgentState(
            user_request=request,
            orchestration_mode=orch_mode,
        )
        activity_log: List[AgentActivityLogItem] = []

        # -------------------------------------------------------------
        # STEP 1: REQUEST & PARAMETER PARSING
        # -------------------------------------------------------------
        activity_log.append(
            AgentActivityLogItem(
                step=1,
                tool="request_parser",
                status="COMPLETED",
                summary=f"Parsed user request: '{request[:80]}...'",
            )
        )

        try:
            parsed_params = await client.parse_query(request)
        except Exception as e:
            logger.error(f"Error parsing request '{request}': {e}")
            state.errors.append(f"Request parsing error: {str(e)}")
            return cls._build_early_exit_response(state, activity_log, status="failed", action="REJECT_MALFORMED_QUERY")

        aoi_search_name = parsed_params.get("aoi_name")
        before_year = parsed_params.get("before_year")
        after_year = parsed_params.get("after_year")
        radius_m = parsed_params.get("radius_m", proximity_radius_m)
        ndvi_thresh = parsed_params.get("threshold", threshold)

        # -------------------------------------------------------------
        # STEP 2: IDENTIFY AOI
        # -------------------------------------------------------------
        aoi_tool_res: ToolResult = await tool_registry.execute(
            name="get_aoi",
            parameters={"name": aoi_search_name} if aoi_search_name else {},
            db=db,
        )

        if not aoi_tool_res.success or not aoi_tool_res.data:
            state.errors.append(f"Could not identify Area of Interest for '{request}'. Unrecognized AOI.")
            activity_log.append(
                AgentActivityLogItem(
                    step=2,
                    tool="get_aoi",
                    status="FAILED",
                    summary=aoi_tool_res.summary or "AOI resolution failed",
                )
            )
            return cls._build_early_exit_response(
                state,
                activity_log,
                status="rejected",
                action="REJECT_UNRECOGNIZED_AOI",
                reasoning="The requested geographic area could not be matched against cataloged Areas of Interest.",
            )

        state.selected_aoi = aoi_tool_res.data
        aoi_id = uuid.UUID(state.selected_aoi["id"])
        aoi_name = state.selected_aoi.get("name", "Unknown AOI")

        activity_log.append(
            AgentActivityLogItem(
                step=2,
                tool="get_aoi",
                status="COMPLETED",
                summary=f"Resolved AOI '{aoi_name}' (ID: {aoi_id})",
            )
        )

        # -------------------------------------------------------------
        # STEP 3: IDENTIFY SCENES
        # -------------------------------------------------------------
        scenes_tool_res: ToolResult = await tool_registry.execute(
            name="list_scenes",
            parameters={
                "aoi_id": aoi_id,
                "before_year": before_year,
                "after_year": after_year,
                "max_cloud_cover": 20.0,
            },
            db=db,
        )

        if not scenes_tool_res.success or not scenes_tool_res.data:
            state.errors.append(f"Could not find matching satellite scenes for AOI '{aoi_name}' in {before_year}-{after_year}.")
            activity_log.append(
                AgentActivityLogItem(
                    step=3,
                    tool="list_scenes",
                    status="FAILED",
                    summary=scenes_tool_res.summary or "Scene resolution failed",
                )
            )
            return cls._build_early_exit_response(
                state,
                activity_log,
                status="rejected",
                action="REJECT_UNAVAILABLE_SCENES",
                reasoning=f"No matching satellite scenes found for '{aoi_name}' across the requested observation timeframe.",
            )

        scenes_data = scenes_tool_res.data
        state.before_scene = scenes_data.get("before_scene")
        state.after_scene = scenes_data.get("after_scene")

        if not state.before_scene or not state.after_scene:
            state.errors.append("Baseline or comparison satellite scene is missing.")
            return cls._build_early_exit_response(state, activity_log, status="rejected", action="REJECT_UNAVAILABLE_SCENES")

        before_scene_id = uuid.UUID(state.before_scene["id"])
        after_scene_id = uuid.UUID(state.after_scene["id"])

        activity_log.append(
            AgentActivityLogItem(
                step=3,
                tool="list_scenes",
                status="COMPLETED",
                summary=f"Selected scenes: Baseline {state.before_scene.get('scene_identifier')} -> Comparison {state.after_scene.get('scene_identifier')}",
            )
        )

        # -------------------------------------------------------------
        # STEP 4: RUN ANALYSIS (DETERMINISTIC GIS)
        # -------------------------------------------------------------
        analysis_tool_res: ToolResult = await tool_registry.execute(
            name="run_ndvi_analysis",
            parameters={
                "aoi_id": aoi_id,
                "before_scene_id": before_scene_id,
                "after_scene_id": after_scene_id,
                "threshold": ndvi_thresh,
                "minimum_area_m2": 500.0,
            },
            db=db,
        )

        if not analysis_tool_res.success or not analysis_tool_res.data:
            state.errors.append(f"Deterministic GIS pipeline execution failed: {analysis_tool_res.error}")
            activity_log.append(
                AgentActivityLogItem(
                    step=4,
                    tool="run_ndvi_analysis",
                    status="FAILED",
                    summary=analysis_tool_res.summary,
                )
            )
            return cls._build_early_exit_response(
                state,
                activity_log,
                status="failed",
                action="GIS_PIPELINE_ERROR",
                reasoning=f"Underlying GIS raster processing error: {analysis_tool_res.error}",
            )

        analysis_data = analysis_tool_res.data
        state.analysis_id = analysis_data.get("analysis_id")
        analysis_uuid = uuid.UUID(state.analysis_id)
        metrics = analysis_data.get("metrics", {})
        state.change_area_ha = metrics.get("total_change_area_ha", 0.0)
        state.mean_ndvi_change = metrics.get("mean_ndvi_difference", 0.0)
        state.polygon_count = metrics.get("change_polygon_count", 0)

        activity_log.append(
            AgentActivityLogItem(
                step=4,
                tool="run_ndvi_analysis",
                status="COMPLETED",
                summary=f"NDVI processing complete: {state.change_area_ha:.2f} ha across {state.polygon_count} polygon(s)",
            )
        )

        # -------------------------------------------------------------
        # STEP 5: VALIDATE (DETERMINISTIC QUALITY GATE)
        # -------------------------------------------------------------
        val_tool_res: ToolResult = await tool_registry.execute(
            name="validate_analysis",
            parameters={
                "aoi_id": aoi_id,
                "before_scene_id": before_scene_id,
                "after_scene_id": after_scene_id,
                "analysis_id": analysis_uuid,
                "max_cloud_cover": 20.0,
                "threshold": ndvi_thresh,
                "min_area_m2": 500.0,
            },
            db=db,
        )

        if val_tool_res.success and val_tool_res.data:
            state.validation_result = QualityGateReport(**val_tool_res.data)
        else:
            state.validation_result = QualityGateReport(status="VALIDATION_FAILED", failure_reason="Quality gate execution error")

        if state.validation_result.status == "VALIDATION_FAILED":
            fail_reason = state.validation_result.failure_reason or "Quality checks failed"
            activity_log.append(
                AgentActivityLogItem(
                    step=5,
                    tool="validate_analysis",
                    status="FAILED",
                    summary=f"Quality Gate Failed: {fail_reason}",
                )
            )

            action = "REJECT_UNRELIABLE_IMAGERY" if "cloud" in fail_reason.lower() else "REJECT_QUALITY_CHECK_FAILED"
            status, _, reasoning, evidence = await client.evaluate_decision(state)

            return cls._build_response_from_state(
                state=state,
                activity_log=activity_log,
                status="rejected",
                recommended_action=action,
                reasoning_summary=reasoning,
                evidence=evidence,
            )

        activity_log.append(
            AgentActivityLogItem(
                step=5,
                tool="validate_analysis",
                status="COMPLETED",
                summary=f"Quality Gate Passed: 5/5 checks validated (Cloud cover, radiometric delta, noise filter, AOI containment)",
            )
        )

        # -------------------------------------------------------------
        # STEP 6: SPATIAL IMPACT (POSTGIS PROXIMITY & INTERSECTION)
        # -------------------------------------------------------------
        if state.polygon_count == 0 or state.change_area_ha <= 0.0:
            # Stable canopy case -> no change
            activity_log.append(
                AgentActivityLogItem(
                    step=6,
                    tool="spatial_analysis",
                    status="SKIPPED",
                    summary="No change polygons detected; spatial proximity analysis not required.",
                )
            )
        else:
            # Execute Infrastructure Proximity
            infra_tool_res: ToolResult = await tool_registry.execute(
                name="find_nearby_infrastructure",
                parameters={"analysis_id": analysis_uuid, "radius_m": radius_m},
                db=db,
            )
            if infra_tool_res.success and infra_tool_res.data:
                infra_data = infra_tool_res.data
                state.affected_infrastructure = infra_data.get("infrastructure", [])
                activity_log.append(
                    AgentActivityLogItem(
                        step=6,
                        tool="find_nearby_infrastructure",
                        status="COMPLETED",
                        summary=f"PostGIS Proximity: Found {len(state.affected_infrastructure)} infrastructure asset(s) within {radius_m:.0f}m",
                    )
                )

            # Execute Population Context
            pop_tool_res: ToolResult = await tool_registry.execute(
                name="get_population_context",
                parameters={"analysis_id": analysis_uuid, "radius_m": radius_m},
                db=db,
            )
            if pop_tool_res.success and pop_tool_res.data:
                state.affected_population_context = pop_tool_res.data
                inter_pop = state.affected_population_context.get("total_intersecting_population", 0)
                activity_log.append(
                    AgentActivityLogItem(
                        step=7,
                        tool="get_population_context",
                        status="COMPLETED",
                        summary=f"Demographic Context: {inter_pop:,} residents in intersecting settlement zones",
                    )
                )

        # -------------------------------------------------------------
        # STEP 7: DECISION & OBJECTIVE SYNTHESIS
        # -------------------------------------------------------------
        dec_status, dec_action, dec_reasoning, dec_evidence = await client.evaluate_decision(state)

        activity_log.append(
            AgentActivityLogItem(
                step=8,
                tool="decision_engine",
                status="COMPLETED",
                summary=f"Decision: {dec_status.upper()} -> Recommended Action: {dec_action}",
            )
        )

        return cls._build_response_from_state(
            state=state,
            activity_log=activity_log,
            status=dec_status,
            recommended_action=dec_action,
            reasoning_summary=dec_reasoning,
            evidence=dec_evidence,
        )

    @classmethod
    def _build_response_from_state(
        cls,
        state: AgentState,
        activity_log: List[AgentActivityLogItem],
        status: str,
        recommended_action: str,
        reasoning_summary: str,
        evidence: List[str],
    ) -> AgentAnalyzeResponse:
        """Assemble standardized AgentAnalyzeResponse."""
        aoi_name = (state.selected_aoi or {}).get("name")
        aoi_id_str = (state.selected_aoi or {}).get("id")

        period = AnalysisPeriod(
            before=(state.before_scene or {}).get("acquisition_date"),
            after=(state.after_scene or {}).get("acquisition_date"),
        )

        change = ChangeMetricsSummary(
            area_ha=round(state.change_area_ha or 0.0, 2),
            mean_ndvi_change=round(state.mean_ndvi_change or 0.0, 4),
            polygon_count=state.polygon_count or 0,
        )

        infra_list = state.affected_infrastructure or []
        pop_ctx = state.affected_population_context or {}
        spatial_impact = SpatialImpactSummary(
            infrastructure_count=len(infra_list),
            population_context=pop_ctx,
            infrastructure=infra_list,
        )

        val_report = state.validation_result
        val_summary = ValidationSummary(
            passed=val_report.status == "PASSED" if val_report else False,
            reasons=[val_report.failure_reason] if (val_report and val_report.failure_reason) else [
                c.description for c in (val_report.gate_checks if val_report else [])
            ],
            checks=[c.model_dump() for c in (val_report.gate_checks if val_report else [])],
        )

        return AgentAnalyzeResponse(
            status=status,
            aoi=aoi_name,
            aoi_id=aoi_id_str,
            analysis_id=state.analysis_id,
            analysis_period=period,
            change=change,
            spatial_impact=spatial_impact,
            validation=val_summary,
            recommended_action=recommended_action,
            evidence=evidence,
            orchestration_mode=state.orchestration_mode,
            reasoning_summary=reasoning_summary,
            activity_log=activity_log,
        )

    @classmethod
    def _build_early_exit_response(
        cls,
        state: AgentState,
        activity_log: List[AgentActivityLogItem],
        status: str = "rejected",
        action: str = "NO_ACTION_REQUIRED",
        reasoning: str = "",
    ) -> AgentAnalyzeResponse:
        """Helper for early termination responses."""
        return cls._build_response_from_state(
            state=state,
            activity_log=activity_log,
            status=status,
            recommended_action=action,
            reasoning_summary=reasoning or "; ".join(state.errors),
            evidence=state.errors.copy(),
        )

    # -------------------------------------------------------------
    # Legacy Multi-Step Plan Orchestration (Backward Compatibility)
    # -------------------------------------------------------------
    @staticmethod
    def _resolve_variables(parameters: Dict[str, Any], variables: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively replace $variable references in parameter dictionaries."""
        resolved: Dict[str, Any] = {}
        for k, v in parameters.items():
            if isinstance(v, str) and v.startswith("$"):
                var_key = v[1:]
                if var_key in variables:
                    resolved[k] = variables[var_key]
                elif v in variables:
                    resolved[k] = variables[v]
                else:
                    resolved[k] = v
            elif isinstance(v, dict):
                resolved[k] = AgentOrchestrator._resolve_variables(v, variables)
            else:
                resolved[k] = v
        return resolved

    @classmethod
    async def execute_query(
        cls,
        query: str,
        db: AsyncSession,
        provider: Optional[str] = None,
    ) -> AgentResponse:
        """Legacy execution method for POST /api/agent/query."""
        try:
            plan = await AgentPlanner.create_plan(query=query, db=db, provider=provider)
        except Exception as e:
            logger.error(f"Planning failed for query '{query}': {e}", exc_info=True)
            return AgentResponse(
                query=query,
                status="PLANNING_FAILED",
                plan=AnalysisPlan(query=query, steps=[]),
                quality_report=QualityGateReport(
                    status="VALIDATION_FAILED",
                    failure_reason=f"Planning error: {str(e)}",
                ),
                explanation=f"Could not generate a valid geospatial analysis plan: {str(e)}",
            )

        variables: Dict[str, Any] = {
            "threshold": plan.parameters.get("threshold", -0.20),
            "minimum_area_m2": plan.parameters.get("minimum_area_m2", 500.0),
            "proximity_radius_m": plan.parameters.get("proximity_radius_m", 1000.0),
            "max_cloud_cover": plan.parameters.get("max_cloud_cover", 20.0),
        }
        step_results: Dict[str, Any] = {}
        activity_log: List[AgentActivityLogItem] = []
        overall_status = "COMPLETED"
        quality_report = QualityGateReport(status="PASSED")
        analysis_id_str: Optional[str] = None
        aoi_data: Optional[Dict[str, Any]] = None

        for step in plan.steps:
            resolved_params = cls._resolve_variables(step.parameters, variables)

            tool_res: ToolResult = await tool_registry.execute(
                name=step.tool,
                parameters=resolved_params,
                db=db,
            )

            if not tool_res.success:
                step.status = "FAILED"
                overall_status = "EXECUTION_FAILED"
                activity_log.append(
                    AgentActivityLogItem(
                        step=step.step_number,
                        tool=step.tool,
                        status="FAILED",
                        summary=tool_res.summary,
                    )
                )
                logger.warning(f"Step {step.step_number} ({step.tool}) failed: {tool_res.error}")
                break

            step.status = "COMPLETED"
            step_results[step.tool] = tool_res.data
            activity_log.append(
                AgentActivityLogItem(
                    step=step.step_number,
                    tool=step.tool,
                    status="COMPLETED",
                    summary=tool_res.summary,
                )
            )

            if step.tool in ("get_aoi", "list_aois") and isinstance(tool_res.data, dict):
                aoi_data = tool_res.data
                variables["aoi_id"] = uuid.UUID(tool_res.data["id"]) if isinstance(tool_res.data["id"], str) else tool_res.data["id"]
                variables["aoi_name"] = tool_res.data.get("name")
            elif step.tool in ("list_scenes", "get_satellite_metadata") and isinstance(tool_res.data, dict):
                before = tool_res.data.get("before_scene")
                after = tool_res.data.get("after_scene")
                if before:
                    variables["before_scene_id"] = uuid.UUID(before["id"]) if isinstance(before["id"], str) else before["id"]
                if after:
                    variables["after_scene_id"] = uuid.UUID(after["id"]) if isinstance(after["id"], str) else after["id"]
            elif step.tool in ("run_ndvi_analysis", "run_ndvi_change_pipeline") and isinstance(tool_res.data, dict):
                analysis_id_str = tool_res.data.get("analysis_id")
                if analysis_id_str:
                    variables["analysis_id"] = uuid.UUID(analysis_id_str)
            elif step.tool == "validate_analysis" and isinstance(tool_res.data, dict):
                quality_report = QualityGateReport(**tool_res.data)
                if quality_report.status == "VALIDATION_FAILED":
                    overall_status = "VALIDATION_FAILED"
                    activity_log.append(
                        AgentActivityLogItem(
                            step="quality_gate",
                            tool="validate_analysis",
                            status="VALIDATION_FAILED",
                            summary=f"Quality Gate Failed: {quality_report.failure_reason}",
                        )
                    )
                    break

        pipeline_res = step_results.get("run_ndvi_analysis", {}) or step_results.get("run_ndvi_change_pipeline", {})
        metrics = pipeline_res.get("metrics")
        infra_res = step_results.get("find_nearby_infrastructure", {})
        nearby_infra_list = infra_res.get("infrastructure") if isinstance(infra_res, dict) else (infra_res if isinstance(infra_res, list) else None)
        pop_res = step_results.get("get_population_context") or step_results.get("analyze_population_proximity")

        client = get_llm_client(provider=provider)
        explanation = await client.synthesize_explanation(
            query=query,
            plan=plan,
            results=step_results,
        )

        return AgentResponse(
            query=query,
            status=overall_status,
            analysis_id=analysis_id_str,
            aoi=aoi_data,
            plan=plan,
            metrics=metrics,
            nearby_infrastructure=nearby_infra_list,
            population_context=pop_res,
            quality_report=quality_report,
            activity_log=activity_log,
            explanation=explanation,
        )
