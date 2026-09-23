"""TerraLens Agent Data Models and Pydantic Schemas.

Defines schemas for:
- AnalysisPlan and PlanStep
- ToolCall and ToolResult
- ExecutionContext and ActivityLog
- QualityGateReport
- AgentQueryRequest, AgentPlanRequest, AgentResponse
- AgentState, AgentAnalyzeRequest, AgentAnalyzeResponse, AgentHealthResponse
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


# --- Legacy / Multi-Step Plan Models ---

class PlanStep(BaseModel):
    step_number: int = Field(..., description="1-indexed sequence number of the step")
    tool: str = Field(..., description="Allowlisted tool name to invoke")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters to pass to the tool. May contain variable references like $aoi_id")
    description: str = Field(..., description="Human-readable rationale for this plan step")
    status: str = Field(default="PENDING", description="Step status: PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED")


class AnalysisPlan(BaseModel):
    query: str = Field(..., description="Original user natural language query")
    intent: str = Field(default="VEGETATION_CHANGE_AND_PROXIMITY", description="Classified geospatial intent")
    aoi_name: Optional[str] = Field(None, description="Resolved Area of Interest name")
    aoi_id: Optional[str] = Field(None, description="Resolved Area of Interest UUID")
    timeframe: Dict[str, Optional[int]] = Field(
        default_factory=lambda: {"before_year": None, "after_year": None},
        description="Temporal comparison timeframe",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=lambda: {
            "threshold": -0.20,
            "minimum_area_m2": 500.0,
            "proximity_radius_m": 1000.0,
            "max_cloud_cover": 20.0,
        },
        description="Analysis configuration parameters",
    )
    steps: List[PlanStep] = Field(default_factory=list, description="Ordered sequence of execution steps")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ToolParameterSchema(BaseModel):
    name: str
    description: str
    parameters_schema: Dict[str, Any]


class ToolResult(BaseModel):
    success: bool
    tool_name: str
    data: Any = None
    summary: str = ""
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentActivityLogItem(BaseModel):
    step: Union[int, str]
    tool: Optional[str] = None
    status: str = "COMPLETED"
    summary: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Optional[Dict[str, Any]] = None


class GateCheckDetail(BaseModel):
    gate_name: str
    status: str  # "PASSED" or "FAILED"
    description: str
    value: Any = None
    threshold: Any = None


class QualityGateReport(BaseModel):
    status: str = "PASSED"  # "PASSED", "VALIDATION_FAILED"
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    gate_checks: List[GateCheckDetail] = Field(default_factory=list)
    failure_reason: Optional[str] = None
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, description="Natural language geospatial query")
    llm_provider: Optional[str] = Field(None, description="Optional override for LLM provider (mock, gemini, openai)")


class AgentPlanRequest(BaseModel):
    query: str = Field(..., min_length=3, description="Natural language query to plan without executing")


class AgentResponse(BaseModel):
    query: str
    status: str  # "COMPLETED", "VALIDATION_FAILED", "PLANNING_FAILED", "EXECUTION_FAILED"
    analysis_id: Optional[str] = None
    aoi: Optional[Dict[str, Any]] = None
    plan: AnalysisPlan
    metrics: Optional[Dict[str, Any]] = None
    nearby_infrastructure: Optional[List[Dict[str, Any]]] = None
    population_context: Optional[Dict[str, Any]] = None
    quality_report: QualityGateReport
    activity_log: List[AgentActivityLogItem] = Field(default_factory=list)
    explanation: str
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --- Phase 4 State & Orchestration Models ---

class AnalysisPeriod(BaseModel):
    before: Optional[str] = None
    after: Optional[str] = None


class ChangeMetricsSummary(BaseModel):
    area_ha: float = 0.0
    mean_ndvi_change: float = 0.0
    polygon_count: int = 0


class SpatialImpactSummary(BaseModel):
    infrastructure_count: int = 0
    population_context: Dict[str, Any] = Field(default_factory=dict)
    infrastructure: List[Dict[str, Any]] = Field(default_factory=list)


class ValidationSummary(BaseModel):
    passed: bool = False
    reasons: List[str] = Field(default_factory=list)
    checks: List[Dict[str, Any]] = Field(default_factory=list)


class AgentState(BaseModel):
    """Typed runtime execution state of the TerraLens Agent."""
    user_request: str
    selected_aoi: Optional[Dict[str, Any]] = None
    before_scene: Optional[Dict[str, Any]] = None
    after_scene: Optional[Dict[str, Any]] = None
    analysis_id: Optional[str] = None
    validation_result: Optional[QualityGateReport] = None
    change_area_ha: Optional[float] = None
    mean_ndvi_change: Optional[float] = None
    polygon_count: Optional[int] = None
    affected_infrastructure: Optional[List[Dict[str, Any]]] = None
    affected_population_context: Optional[Dict[str, Any]] = None
    final_decision: str = "PENDING"  # "actionable", "not_actionable", "rejected", "unvalidated", "failed"
    decision_status: str = "detected"  # "detected", "validated", "significant", "actionable", "rejected"
    recommended_action: str = "NO_ACTION_REQUIRED"
    reasoning_summary: str = ""
    errors: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    status: str = "PENDING"
    orchestration_mode: str = "deterministic_demo"


class AgentAnalyzeRequest(BaseModel):
    """Incoming request payload for POST /api/agent/analyze."""
    request: str = Field(..., min_length=3, description="Natural language environmental monitoring query")
    llm_provider: Optional[str] = Field(None, description="LLM provider: gemini, openai, anthropic, local, or mock")
    proximity_radius_m: Optional[float] = Field(1000.0, description="Spatial search radius for infrastructure proximity in meters")
    threshold: Optional[float] = Field(-0.20, description="NDVI decrease change threshold")


class AgentAnalyzeResponse(BaseModel):
    """Structured response schema returned by POST /api/agent/analyze."""
    status: str = Field(..., description="'validated', 'detected', 'rejected', 'not_actionable', or 'failed'")
    aoi: Optional[str] = Field(None, description="Resolved official Area of Interest name")
    aoi_id: Optional[str] = Field(None, description="Resolved AOI UUID")
    analysis_id: Optional[str] = Field(None, description="PostGIS analysis run UUID")
    analysis_period: AnalysisPeriod = Field(default_factory=AnalysisPeriod)
    change: ChangeMetricsSummary = Field(default_factory=ChangeMetricsSummary)
    spatial_impact: SpatialImpactSummary = Field(default_factory=SpatialImpactSummary)
    validation: ValidationSummary = Field(default_factory=ValidationSummary)
    recommended_action: str = Field(..., description="Actionable directive (e.g. ISSUE_MONITORING_ALERT, NO_ACTION_REQUIRED, REJECT_UNRELIABLE_IMAGERY)")
    evidence: List[str] = Field(default_factory=list, description="List of factual, non-causal evidence statements")
    orchestration_mode: str = Field("deterministic_demo", description="'llm' or 'deterministic_demo'")
    reasoning_summary: str = Field("", description="Concise non-causal reasoning summary")
    activity_log: List[AgentActivityLogItem] = Field(default_factory=list)
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentHealthResponse(BaseModel):
    """Healthcheck response for GET /api/agent/health."""
    status: str = "online"
    agent_layer: str = "TerraLens Agent Orchestrator v1.0"
    configured_llm_provider: str
    is_demo_mode: bool
    registered_tools_count: int
    tools: List[str]
    database_connected: bool
