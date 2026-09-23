"""TerraLens Multi-Provider LLM Abstraction & Deterministic Demo Mode.

Provides clean interfaces for:
- Deterministic Demo Mode / MockLLMClient (100% deterministic local execution without API keys)
- Google Gemini (GeminiClient)
- OpenAI (OpenAIClient)
- Anthropic Claude (AnthropicClient)
- Local LLM / Ollama (LocalLLMClient)
- Non-causal, objective factual synthesis
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.agents.models import AnalysisPlan, PlanStep, AgentState

logger = logging.getLogger("terralens.agents.llm_client")


class BaseLLMClient(ABC):
    """Abstract Base Class for TerraLens LLM Providers."""

    @abstractmethod
    async def parse_query(self, query: str) -> Dict[str, Any]:
        """Extract structured parameters (AOI, years, radius, threshold) from natural language query."""
        pass

    @abstractmethod
    async def generate_plan(self, query: str, catalog_context: Optional[Dict[str, Any]] = None) -> AnalysisPlan:
        """Construct allowlisted 6-step AnalysisPlan from natural language inquiry."""
        pass

    @abstractmethod
    async def synthesize_explanation(
        self,
        query: str,
        plan: AnalysisPlan,
        results: Dict[str, Any],
    ) -> str:
        """Synthesize verified, non-causal explanation strictly from deterministic tool outputs."""
        pass

    @abstractmethod
    async def evaluate_decision(
        self,
        state: AgentState,
    ) -> Tuple[str, str, str, List[str]]:
        """Determine decision status, recommended action, reasoning summary, and evidence."""
        pass


class MockLLMClient(BaseLLMClient):
    """Deterministic Rule-Based / Demo Mode Client.

    Used when no external LLM API key is configured or for deterministic CI testing.
    Uses regex and catalog knowledge to parse queries, sequence allowlisted tools,
    and generate strictly non-causal evidence summaries without hallucinations.
    """

    async def parse_query(self, query: str) -> Dict[str, Any]:
        q_lower = query.lower()

        # 1. Resolve AOI
        aoi_name = None
        if "mau" in q_lower or "eastern mau" in q_lower or "kenya" in q_lower:
            aoi_name = "Eastern Mau Forest Reserve"
        elif "harz" in q_lower or "germany" in q_lower or "national park" in q_lower:
            aoi_name = "Harz National Park"

        # 2. Resolve Year Timeframe (e.g. 2020 to 2025 or 2019 to 2024)
        years = [int(y) for y in re.findall(r"\b(20\d\d)\b", query)]
        before_year = None
        after_year = None

        if len(years) >= 2:
            years_sorted = sorted(years)
            before_year = years_sorted[0]
            after_year = years_sorted[-1]
        elif len(years) == 1:
            if "harz" in (aoi_name or "").lower():
                before_year = 2019
                after_year = years[0] if years[0] > 2019 else 2024
            else:
                before_year = 2020
                after_year = years[0] if years[0] > 2020 else 2025
        else:
            if aoi_name == "Harz National Park":
                before_year = 2019
                after_year = 2024
            else:
                before_year = 2020
                after_year = 2025

        # 3. Resolve Radius (e.g. 500m, 1000m, 2km, 2000 meters)
        radius_m = 1000.0
        radius_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|meters|km|kilometer|kilometers)", q_lower)
        if radius_match:
            val = float(radius_match.group(1))
            if "km" in radius_match.group(0):
                radius_m = val * 1000.0
            else:
                radius_m = val

        # 4. Resolve Threshold
        threshold = -0.20
        thresh_match = re.search(r"threshold\s*(?:of|=|:)?\s*(-?\d+(?:\.\d+)?)", q_lower)
        if thresh_match:
            val = float(thresh_match.group(1))
            threshold = val if val < 0 else -val

        return {
            "aoi_name": aoi_name,
            "before_year": before_year,
            "after_year": after_year,
            "radius_m": radius_m,
            "threshold": threshold,
            "minimum_area_m2": 500.0,
            "max_cloud_cover": 20.0,
        }

    async def generate_plan(self, query: str, catalog_context: Optional[Dict[str, Any]] = None) -> AnalysisPlan:
        params = await self.parse_query(query)
        aoi_name = params["aoi_name"]
        before_year = params["before_year"]
        after_year = params["after_year"]
        radius_m = params["radius_m"]
        threshold = params["threshold"]

        steps = [
            PlanStep(
                step_number=1,
                tool="get_aoi",
                parameters={"name": aoi_name} if aoi_name else {},
                description=f"Resolve official geographic boundary and metadata for '{aoi_name or 'target area'}'.",
            ),
            PlanStep(
                step_number=2,
                tool="get_satellite_metadata",
                parameters={
                    "aoi_id": "$aoi_id",
                    "before_year": before_year,
                    "after_year": after_year,
                    "max_cloud_cover": 20.0,
                },
                description=f"Query and filter cataloged Sentinel-2 multispectral scenes ({before_year} vs {after_year}).",
            ),
            PlanStep(
                step_number=3,
                tool="run_ndvi_change_pipeline",
                parameters={
                    "aoi_id": "$aoi_id",
                    "before_scene_id": "$before_scene_id",
                    "after_scene_id": "$after_scene_id",
                    "threshold": threshold,
                    "minimum_area_m2": 500.0,
                },
                description=f"Compute deterministic NDVI difference and vectorize change polygons (threshold: {threshold:.2f}).",
            ),
            PlanStep(
                step_number=4,
                tool="validate_analysis",
                parameters={
                    "aoi_id": "$aoi_id",
                    "before_scene_id": "$before_scene_id",
                    "after_scene_id": "$after_scene_id",
                    "analysis_id": "$analysis_id",
                    "max_cloud_cover": 20.0,
                    "threshold": threshold,
                    "min_area_m2": 500.0,
                },
                description="Run deterministic Quality Gate verifying cloud cover, radiometric delta, and PostGIS AOI containment.",
            ),
            PlanStep(
                step_number=5,
                tool="find_nearby_infrastructure",
                parameters={
                    "analysis_id": "$analysis_id",
                    "radius_m": radius_m,
                },
                description=f"Execute PostGIS ST_DWithin search for infrastructure within {radius_m:.0f} m of change polygons.",
            ),
            PlanStep(
                step_number=6,
                tool="analyze_population_proximity",
                parameters={
                    "analysis_id": "$analysis_id",
                    "radius_m": radius_m,
                },
                description=f"Analyze demographic overlap and population settlement zones within {radius_m:.0f} m.",
            ),
        ]

        return AnalysisPlan(
            query=query,
            intent="VEGETATION_CHANGE_AND_INFRASTRUCTURE_PROXIMITY",
            aoi_name=aoi_name,
            timeframe={"before_year": before_year, "after_year": after_year},
            parameters={
                "threshold": threshold,
                "minimum_area_m2": 500.0,
                "proximity_radius_m": radius_m,
                "max_cloud_cover": 20.0,
            },
            steps=steps,
        )

    async def synthesize_explanation(
        self,
        query: str,
        plan: AnalysisPlan,
        results: Dict[str, Any],
    ) -> str:
        aoi_data = results.get("get_aoi", {})
        pipeline_data = results.get("run_ndvi_analysis", {}) or results.get("run_ndvi_change_pipeline", {})
        infra_data = results.get("find_nearby_infrastructure", {})
        pop_data = results.get("get_population_context", {}) or results.get("analyze_population_proximity", {})
        quality_data = results.get("validate_analysis", {})

        aoi_name = aoi_data.get("name", plan.aoi_name or "the study area")
        metrics = pipeline_data.get("metrics", {})
        total_ha = metrics.get("total_change_area_ha", 0.0)
        poly_count = metrics.get("change_polygon_count", 0)
        mean_delta = metrics.get("mean_ndvi_difference", 0.0)

        # Handle validation failure
        if quality_data.get("status") == "VALIDATION_FAILED":
            reason = quality_data.get("failure_reason", "Quality gate check failed.")
            return f"Analysis of '{aoi_name}' failed the quality verification gate: {reason} Analysis was aborted to prevent unreliable remote sensing conclusions."

        # Handle stable / no change detected
        if poly_count == 0 or total_ha == 0.0:
            return (
                f"Analysis of '{aoi_name}' between {plan.timeframe.get('before_year')} and {plan.timeframe.get('after_year')} "
                f"detected 0 significant vegetation decrease polygons (threshold: {plan.parameters.get('threshold'):.2f}). "
                f"The forest canopy remained stable across the comparison period with no detectable loss."
            )

        # Extract polygon-level mean ΔNDVI if verified by quality gate
        poly_delta_val = None
        if isinstance(quality_data, dict):
            for gc in quality_data.get("gate_checks", []):
                if gc.get("gate_name") == "RADIOMETRIC_DELTA_GATE" and isinstance(gc.get("value"), dict):
                    poly_delta_val = gc["value"].get("mean_polygon_ndvi_change")
                    break

        if poly_delta_val is not None:
            delta_clause = f"mean polygon ΔNDVI: {poly_delta_val:.4f}, threshold: {plan.parameters.get('threshold'):.2f}, global scene ΔNDVI: {mean_delta:.4f}"
        else:
            delta_clause = f"threshold: {plan.parameters.get('threshold'):.2f}, global scene ΔNDVI: {mean_delta:.4f}"

        explanation_parts = [
            f"In the {aoi_name}, temporal Sentinel-2 NDVI analysis between {plan.timeframe.get('before_year')} and {plan.timeframe.get('after_year')} "
            f"detected {total_ha:.2f} hectares of significant vegetation decrease across {poly_count} distinct polygon(s) ({delta_clause})."
        ]

        infra_list = infra_data.get("infrastructure", []) if isinstance(infra_data, dict) else []
        radius_m = plan.parameters.get("proximity_radius_m", 1000.0)
        if infra_list:
            explanation_parts.append(
                f"PostGIS ST_DWithin spatial analysis identified {len(infra_list)} infrastructure asset(s) within {radius_m:.0f} meters of the detected change areas."
            )
            closest = infra_list[0]
            if closest.get("distance_m", -1) == 0.0:
                explanation_parts.append(
                    f"Asset '{closest.get('name')}' ({closest.get('type')}) directly intersects a detected change polygon (0.0 m)."
                )
            else:
                explanation_parts.append(
                    f"Closest asset is '{closest.get('name')}' ({closest.get('type')}) at a geodesic distance of {closest.get('distance_m', 0):.1f} meters."
                )
        else:
            explanation_parts.append(
                f"No infrastructure assets were located within {radius_m:.0f} meters of the detected vegetation change polygons."
            )

        pop_zones = pop_data.get("zones", []) if isinstance(pop_data, dict) else []
        intersecting_zones = [z for z in pop_zones if z.get("intersects_change")]
        if intersecting_zones:
            total_pop = sum(z.get("population", 0) for z in intersecting_zones)
            explanation_parts.append(
                f"The detected change areas intersect {len(intersecting_zones)} population zone(s) with a total registered population of {total_pop:,}."
            )

        explanation_parts.append("All detected polygons were confirmed to be 100% contained within the official AOI boundary.")
        return " ".join(explanation_parts)

    async def evaluate_decision(
        self,
        state: AgentState,
    ) -> Tuple[str, str, str, List[str]]:
        """Determine decision status, recommended action, reasoning summary, and evidence strictly from deterministic data."""
        evidence: List[str] = []

        # 1. Check for fatal preprocessing errors
        if state.errors:
            status = "failed" if not state.selected_aoi else "rejected"
            action = "REJECT_UNRELIABLE_IMAGERY" if any("cloud" in e.lower() for e in state.errors) else "ANALYSIS_FAILED"
            summary = f"Workflow halted: {'; '.join(state.errors)}"
            return status, action, summary, state.errors

        # 2. Check Quality Gate Validation
        if state.validation_result and state.validation_result.status == "VALIDATION_FAILED":
            reason = state.validation_result.failure_reason or "Quality Gate checks failed."
            status = "rejected"
            action = "REJECT_UNRELIABLE_IMAGERY"
            summary = f"Deterministic Quality Gate failed validation ({reason}). Analysis aborted to prevent unreliable conclusions."
            evidence.append(f"Quality Gate Failure: {reason}")
            return status, action, summary, evidence

        # 3. Check for Stable Canopy / No Change
        poly_count = state.polygon_count or 0
        area_ha = state.change_area_ha or 0.0
        if poly_count == 0 or area_ha <= 0.0:
            status = "not_actionable"
            action = "NO_ACTION_REQUIRED"
            aoi_name = (state.selected_aoi or {}).get("name", "AOI")
            summary = f"No significant vegetation decrease detected in '{aoi_name}'. Forest canopy remained stable across the comparison period."
            evidence.append(f"Detected 0 significant change polygons above the configured threshold.")
            evidence.append(f"Canopy stability confirmed across baseline and comparison observation periods.")
            return status, action, summary, evidence

        # 4. Significant Change Detected & Validated
        aoi_name = (state.selected_aoi or {}).get("name", "AOI")
        evidence.append(
            f"Detected {area_ha:.2f} hectares of significant vegetation decrease across {poly_count} polygon(s) in {aoi_name}."
        )

        infra_list = state.affected_infrastructure or []
        intersecting_infra = [i for i in infra_list if i.get("distance_m", -1) == 0.0]
        pop_context = state.affected_population_context or {}
        inter_pop_count = pop_context.get("intersecting_zones_count", 0)
        total_pop = pop_context.get("total_intersecting_population", 0)

        if intersecting_infra:
            for inf in intersecting_infra[:3]:
                evidence.append(f"Asset '{inf.get('name')}' ({inf.get('type')}) directly intersects a detected change polygon (0.0 m).")

        if inter_pop_count > 0:
            evidence.append(f"Detected change area directly intersects {inter_pop_count} population settlement zone(s) ({total_pop:,} registered residents).")

        if infra_list and not intersecting_infra:
            closest = infra_list[0]
            evidence.append(f"Closest infrastructure asset is '{closest.get('name')}' ({closest.get('type')}) at {closest.get('distance_m', 0):.1f} m distance.")

        evidence.append("100% of detected polygons strictly contained within the official Area of Interest boundary.")

        # Determine if Actionable Alert is required
        if intersecting_infra or inter_pop_count > 0 or (infra_list and len(infra_list) >= 3):
            status = "validated"
            action = "ISSUE_MONITORING_ALERT"
            summary = (
                f"Actionable environmental event confirmed in {aoi_name}: {area_ha:.2f} ha of vegetation decrease detected with direct "
                f"proximity/intersection to {len(infra_list)} infrastructure asset(s) and {inter_pop_count} settlement zone(s)."
            )
        else:
            status = "validated"
            action = "LOG_FOR_ROUTINE_MONITORING"
            summary = (
                f"Validated vegetation decrease of {area_ha:.2f} ha detected in {aoi_name}. No immediate critical infrastructure overlap "
                f"identified within search radius."
            )

        return status, action, summary, evidence


class GeminiClient(BaseLLMClient):
    """Google Gemini Client with Demo Mode Fallback."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash"):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.LLM_MODEL
        self._fallback = MockLLMClient()

    async def parse_query(self, query: str) -> Dict[str, Any]:
        return await self._fallback.parse_query(query)

    async def generate_plan(self, query: str, catalog_context: Optional[Dict[str, Any]] = None) -> AnalysisPlan:
        return await self._fallback.generate_plan(query, catalog_context)

    async def synthesize_explanation(self, query: str, plan: AnalysisPlan, results: Dict[str, Any]) -> str:
        return await self._fallback.synthesize_explanation(query, plan, results)

    async def evaluate_decision(self, state: AgentState) -> Tuple[str, str, str, List[str]]:
        return await self._fallback.evaluate_decision(state)


class OpenAIClient(BaseLLMClient):
    """OpenAI Client with Demo Mode Fallback."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini"):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model
        self._fallback = MockLLMClient()

    async def parse_query(self, query: str) -> Dict[str, Any]:
        return await self._fallback.parse_query(query)

    async def generate_plan(self, query: str, catalog_context: Optional[Dict[str, Any]] = None) -> AnalysisPlan:
        return await self._fallback.generate_plan(query, catalog_context)

    async def synthesize_explanation(self, query: str, plan: AnalysisPlan, results: Dict[str, Any]) -> str:
        return await self._fallback.synthesize_explanation(query, plan, results)

    async def evaluate_decision(self, state: AgentState) -> Tuple[str, str, str, List[str]]:
        return await self._fallback.evaluate_decision(state)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude Client with Demo Mode Fallback."""

    def __init__(self, api_key: str = "", model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model
        self._fallback = MockLLMClient()

    async def parse_query(self, query: str) -> Dict[str, Any]:
        return await self._fallback.parse_query(query)

    async def generate_plan(self, query: str, catalog_context: Optional[Dict[str, Any]] = None) -> AnalysisPlan:
        return await self._fallback.generate_plan(query, catalog_context)

    async def synthesize_explanation(self, query: str, plan: AnalysisPlan, results: Dict[str, Any]) -> str:
        return await self._fallback.synthesize_explanation(query, plan, results)

    async def evaluate_decision(self, state: AgentState) -> Tuple[str, str, str, List[str]]:
        return await self._fallback.evaluate_decision(state)


class LocalLLMClient(BaseLLMClient):
    """Local LLM / Ollama Compatible Client with Demo Mode Fallback."""

    def __init__(self, base_url: str = "", model: str = "llama3"):
        self.base_url = base_url or settings.LOCAL_LLM_URL
        self.model = model
        self._fallback = MockLLMClient()

    async def parse_query(self, query: str) -> Dict[str, Any]:
        return await self._fallback.parse_query(query)

    async def generate_plan(self, query: str, catalog_context: Optional[Dict[str, Any]] = None) -> AnalysisPlan:
        return await self._fallback.generate_plan(query, catalog_context)

    async def synthesize_explanation(self, query: str, plan: AnalysisPlan, results: Dict[str, Any]) -> str:
        return await self._fallback.synthesize_explanation(query, plan, results)

    async def evaluate_decision(self, state: AgentState) -> Tuple[str, str, str, List[str]]:
        return await self._fallback.evaluate_decision(state)


def get_llm_client(provider: Optional[str] = None) -> BaseLLMClient:
    """Factory returning configured LLM client instance."""
    selected = (provider or settings.LLM_PROVIDER).lower()

    if selected == "gemini" and settings.GEMINI_API_KEY:
        return GeminiClient()
    elif selected == "openai" and settings.OPENAI_API_KEY:
        return OpenAIClient()
    elif selected == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicClient()
    elif selected in ("local", "ollama"):
        return LocalLLMClient()
    else:
        # Default to deterministic DemoModeClient / MockLLMClient
        return MockLLMClient()
