"""TerraLens Agent Execution Orchestrator.

Coordinates end-to-end plan execution:
1. Generates AnalysisPlan from natural language query
2. Resolves variable references across steps ($aoi_id, $before_scene_id, $analysis_id)
3. Sequentially executes allowlisted tools via ToolRegistry
4. Records structured activity logs
5. Enforces Quality Gate verification
6. Synthesizes factual, verified explanations without hallucination
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    AnalysisPlan,
    AgentResponse,
    AgentActivityLogItem,
    QualityGateReport,
    ToolResult,
)
from app.agents.planner import AgentPlanner
from app.agents.tools import tool_registry
from app.agents.llm_client import get_llm_client

logger = logging.getLogger("terralens.agents.orchestrator")


class AgentOrchestrator:
    """Executes structured geospatial analysis plans using allowlisted GIS/PostGIS tools."""

    @staticmethod
    def _resolve_variables(parameters: Dict[str, Any], variables: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively replace $variable references in parameter dictionaries."""
        resolved: Dict[str, Any] = {}
        for k, v in parameters.items():
            if isinstance(v, str) and v.startswith("$"):
                var_key = v[1:]  # strip leading $
                if var_key in variables:
                    resolved[k] = variables[var_key]
                elif v in variables:
                    resolved[k] = variables[v]
                else:
                    resolved[k] = v  # keep as is if not resolved
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
        """Execute complete agent pipeline from natural language query to verified result."""
        # 1. Generate Plan
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

        # 2. Sequentially Execute Plan Steps
        for step in plan.steps:
            resolved_params = cls._resolve_variables(step.parameters, variables)

            # Invoke Tool via allowlisted ToolRegistry
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

            # Harvest state variables from tool outputs
            if step.tool == "get_aoi" and isinstance(tool_res.data, dict):
                aoi_data = tool_res.data
                variables["aoi_id"] = uuid.UUID(tool_res.data["id"]) if isinstance(tool_res.data["id"], str) else tool_res.data["id"]
                variables["aoi_name"] = tool_res.data.get("name")
            elif step.tool == "get_satellite_metadata" and isinstance(tool_res.data, dict):
                before = tool_res.data.get("before_scene")
                after = tool_res.data.get("after_scene")
                if before:
                    variables["before_scene_id"] = uuid.UUID(before["id"]) if isinstance(before["id"], str) else before["id"]
                if after:
                    variables["after_scene_id"] = uuid.UUID(after["id"]) if isinstance(after["id"], str) else after["id"]
            elif step.tool == "run_ndvi_change_pipeline" and isinstance(tool_res.data, dict):
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

        # 3. Extract Structured Results
        pipeline_res = step_results.get("run_ndvi_change_pipeline", {})
        metrics = pipeline_res.get("metrics")
        infra_res = step_results.get("find_nearby_infrastructure", {})
        nearby_infra_list = infra_res.get("infrastructure") if isinstance(infra_res, dict) else (infra_res if isinstance(infra_res, list) else None)
        pop_res = step_results.get("analyze_population_proximity")

        # 4. Synthesize Verified Explanation
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
