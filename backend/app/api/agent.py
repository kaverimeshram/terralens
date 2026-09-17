"""TerraLens AI Agent API Endpoints.

Provides:
- POST /api/agent/query: End-to-end natural language geospatial inquiry execution
- POST /api/agent/plan: Preview/dry-run analysis plan without execution
- GET  /api/agent/tools: Allowlisted GIS and PostGIS tool catalog & schemas
"""

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_async_db
from app.agents.models import AgentQueryRequest, AgentPlanRequest, AgentResponse, AnalysisPlan
from app.agents.planner import AgentPlanner
from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import tool_registry
from app.gis.validation import GISValidationError

logger = logging.getLogger("terralens.api.agent")

router = APIRouter(prefix="/agent", tags=["AI Agent"])


@router.post("/query", response_model=AgentResponse, status_code=status.HTTP_200_OK)
async def execute_agent_query(
    payload: AgentQueryRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Execute end-to-end natural language geospatial query.

    Translates natural language -> Analysis Plan -> Tool Execution -> Quality Gate -> Verified Explanation.
    """
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
