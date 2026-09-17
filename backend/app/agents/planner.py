"""TerraLens Agent Planner.

Translates natural language user queries into structured, verified AnalysisPlans.
"""

import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AnalysisPlan
from app.agents.llm_client import get_llm_client
from app.agents.tools import tool_registry
from app.gis.validation import GISValidationError

logger = logging.getLogger("terralens.agents.planner")


class AgentPlanner:
    """Coordinates with the LLM / Mock client to generate structured AnalysisPlans."""

    @staticmethod
    async def create_plan(
        query: str,
        db: Optional[AsyncSession] = None,
        provider: Optional[str] = None,
    ) -> AnalysisPlan:
        """Parse natural language query and construct an allowlisted AnalysisPlan."""
        if not query or len(query.strip()) < 3:
            raise GISValidationError("Query must be at least 3 characters long")

        client = get_llm_client(provider=provider)
        plan = await client.generate_plan(query=query)

        # Validate that all plan steps reference registered tools
        for step in plan.steps:
            if not tool_registry.is_registered(step.tool):
                raise GISValidationError(
                    f"Generated plan references unknown tool '{step.tool}'. Tool is not in allowlisted registry."
                )

        return plan
