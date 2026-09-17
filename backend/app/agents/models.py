"""TerraLens Agent Data Models and Pydantic Schemas.

Defines schemas for:
- AnalysisPlan and PlanStep
- ToolCall and ToolResult
- ExecutionContext and ActivityLog
- QualityGateReport
- AgentQueryRequest and AgentResponse
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


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
    summary: str
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
