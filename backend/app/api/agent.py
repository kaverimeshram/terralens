"""TerraLens AI Agent API Endpoints.

Provides:
- POST /api/agent/analyze: Phase 4 end-to-end natural language environmental monitoring analysis
- GET  /api/agent/health: Agent health, LLM provider state, demo mode status, and registered tools
- POST /api/agent/query: Legacy multi-step agent query execution
- POST /api/agent/plan: Preview/dry-run analysis plan without execution
- GET  /api/agent/tools: Allowlisted GIS and PostGIS tool catalog & schemas
"""

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.session import get_async_db
from app.agents.models import (
    AgentAnalyzeRequest,
    AgentAnalyzeResponse,
    AgentHealthResponse,
    AgentQueryRequest,
    AgentPlanRequest,
    AgentResponse,
    AnalysisPlan,
)
from app.agents.planner import AgentPlanner
from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import tool_registry
from app.agents.llm_client import get_llm_client
from app.gis.validation import GISValidationError

logger = logging.getLogger("terralens.api.agent")

router = APIRouter(prefix="/agent", tags=["AI Agent"])


@router.post("/analyze", response_model=AgentAnalyzeResponse, status_code=status.HTTP_200_OK)
async def analyze_environmental_request(
    payload: AgentAnalyzeRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Execute Phase 4 controlled agent workflow for natural language environmental monitoring inquiries.

    Translates: Natural Language -> Resolve AOI & Scenes -> Deterministic NDVI -> Quality Gate -> PostGIS Proximity -> Structured Decision.
    """
    try:
        response = await AgentOrchestrator.analyze(
            request=payload.request,
            db=db,
            provider=payload.llm_provider,
            proximity_radius_m=payload.proximity_radius_m or 1000.0,
            threshold=payload.threshold or -0.20,
        )
        return response
    except GISValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent Validation Error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Agent analysis orchestration error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent Orchestration Error: {str(e)}",
        )


@router.get("/health", response_model=AgentHealthResponse, status_code=status.HTTP_200_OK)
async def check_agent_health(
    db: AsyncSession = Depends(get_async_db),
):
    """Verify health of agent orchestration layer, LLM provider, registered tools, and database."""
    db_connected = False
    try:
        res = await db.execute(text("SELECT 1;"))
        db_connected = res.scalar_one_or_none() == 1
    except Exception as e:
        logger.warning(f"Database health check notice: {e}")

    client = get_llm_client()
    is_demo = getattr(client, "api_key", None) == "" or client.__class__.__name__ == "MockLLMClient"

    return AgentHealthResponse(
        status="online",
        agent_layer="TerraLens Agent Orchestrator v1.0",
        configured_llm_provider=settings.LLM_PROVIDER,
        is_demo_mode=is_demo,
        registered_tools_count=len(tool_registry.get_tool_names()),
        tools=tool_registry.get_tool_names(),
        database_connected=db_connected,
    )


# --- Legacy Endpoints for Full Backward Compatibility ---

@router.post("/query", response_model=AgentResponse, status_code=status.HTTP_200_OK)
async def execute_agent_query(
    payload: AgentQueryRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Legacy query execution endpoint."""
    try:
        response = await AgentOrchestrator.execute_query(
            query=payload.query,
            db=db,
            provider=payload.llm_provider,
        )
        return response
    except GISValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent Validation Error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent Orchestration Error: {str(e)}",
        )


@router.post("/plan", response_model=AnalysisPlan, status_code=status.HTTP_200_OK)
async def generate_agent_plan(
    payload: AgentPlanRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Generate structured Analysis Plan for a natural language query without executing it."""
    try:
        plan = await AgentPlanner.create_plan(
            query=payload.query,
            db=db,
        )
        return plan
    except GISValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Planning Validation Error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Agent planning error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Planning Engine Error: {str(e)}",
        )


@router.get("/tools", status_code=status.HTTP_200_OK)
async def list_agent_tools() -> Dict[str, Any]:
    """Retrieve catalog of allowlisted GIS & PostGIS tools with parameter JSON schemas."""
    catalog = tool_registry.get_catalog()
    return {
        "count": len(catalog),
        "tools": catalog,
    }
