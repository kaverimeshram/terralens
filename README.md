# TerraLens

### AI-Powered Satellite & Spatial Intelligence Agent

TerraLens is an intelligent geospatial agent that converts natural-language remote sensing and geographic inquiries into real GIS analysis workflows, deterministic raster algebra calculations, PostGIS spatial queries, and interactive visual mapping.

> [!NOTE]
> **Dataset Provenance Disclaimer**:
> The development imagery in this repository consists of **synthetic Sentinel-2-like remote-sensing simulation data for development and testing**. It is not raw satellite imagery.

---

## 🛰️ Core Capabilities

- **Natural Language Remote Sensing**: Translates complex spatial inquiries (e.g. *"Analyze vegetation change in Eastern Mau Forest between 2020 and 2025 and find nearby infrastructure"*) into multi-step GIS analysis pipelines.
- **Deterministic GIS Processing**: Uses NumPy, Rasterio, and GeoPandas for radiometric index calculations (NDVI, NDVI Difference, Thresholding, Raster-to-Vector) rather than imprecise LLM approximations.
- **PostGIS Spatial Database**: Real spatial operations (`ST_DWithin`, `ST_Intersects`, `ST_Area`, `ST_Distance`, `ST_Within`, `ST_AsGeoJSON`) on polygon boundaries, population zones, and infrastructure layers with spatial GIST indexing.
- **Rigorous Deterministic Quality Gate**: Enforces physical and remote sensing quality gates (cloud cover thresholds $\le 20\%$, minimum NDVI delta, minimum change area $\ge 500\,\text{m}^2$, AOI containment $= 100\%$) before accepting results.
- **Deterministic Demo Mode**: Fully operational without requiring paid external LLM API keys.
- **Interactive Intelligence Map**: High-performance MapLibre GL UI with vector polygon statistics, infrastructure popups, and proximity overlays.

---

## 🏛️ Phase 4 Architecture & Agent Workflow

```text
User Natural Language Request
        │
        ▼
Agent Orchestration Layer (app/agents/orchestrator.py)
        │
        ├── 1. REQUEST: Initialize typed AgentState
        │
        ├── 2. IDENTIFY AOI: Resolve official boundary & metadata via get_aoi
        │      └── [Early exit if AOI unresolvable]
        │
        ├── 3. IDENTIFY SCENES: Query & filter Sentinel-2 scenes via list_scenes
        │      └── [Early exit if scenes missing or cloud > 20%]
        │
        ├── 4. RUN ANALYSIS: Deterministic band math & vectorization via run_ndvi_analysis
        │      └── (NIR - Red) / (NIR + Red) -> ΔNDVI -> Geodesic polygonization -> PostGIS
        │
        ├── 5. VALIDATE: Execute Quality Gate via validate_analysis
        │      ├── Cloud Cover Gate (≤ 20%)
        │      ├── Radiometric Delta Gate (ΔNDVI ≤ threshold)
        │      ├── Noise Suppression Gate (Area ≥ 500 m²)
        │      └── AOI Containment Gate (ST_Within = 100%)
        │      └── [Early exit if validation fails]
        │
        ├── 6. SPATIAL IMPACT: Query PostGIS proximity via find_nearby_infrastructure & get_population_context
        │      ├── ST_DWithin infrastructure proximity
        │      └── ST_Intersection population demographic overlap
        │
        ├── 7. DECISION: Classify actionability (actionable vs not_actionable)
        │      └── ISSUE_MONITORING_ALERT | NO_ACTION_REQUIRED | REJECT_UNRELIABLE_IMAGERY
        │
        └── 8. RESPONSE: Return verified, non-causal structured JSON payload
```

---

## 🛠️ Tool Registry & Allowlisted GIS Tool Layer

All agent actions execute through an allowlisted, type-safe `ToolRegistry`:

| Tool Name | Parameters | Description |
|---|---|---|
| `list_aois` | `limit: int` | List cataloged Areas of Interest with bounding boxes and surface areas. |
| `get_aoi` | `name: str`, `aoi_id: UUID` | Retrieve official AOI boundary geometry, bounding box, and area. |
| `list_scenes` | `aoi_id: UUID`, `before_year: int`, `after_year: int`, `max_cloud_cover: float` | Query and filter cataloged Sentinel-2 multispectral scenes. |
| `run_ndvi_analysis` | `aoi_id: UUID`, `before_scene_id: UUID`, `after_scene_id: UUID`, `threshold: float` | Execute deterministic raster band math, delta masking, and PostGIS polygonization. |
| `validate_analysis` | `aoi_id: UUID`, `before_scene_id: UUID`, `after_scene_id: UUID`, `analysis_id: UUID` | Execute multi-check deterministic Quality Gate. |
| `calculate_change_area`| `analysis_id: UUID` | PostGIS spatial aggregation calculating total area ($m^2$ and ha) and polygon count. |
| `find_nearby_infrastructure` | `analysis_id: UUID`, `radius_m: float` | PostGIS `ST_DWithin` and `ST_Distance` proximity search for infrastructure. |
| `get_population_context` | `analysis_id: UUID`, `radius_m: float` | PostGIS demographic overlap and population settlement zone analysis. |
| `get_spatial_intersections` | `analysis_id: UUID`, `layer: str` | Exact PostGIS `ST_Intersects` and `ST_Intersection` geometry overlay. |
| `validate_aoi_containment` | `analysis_id: UUID` | Strict `ST_Within` topological containment validation. |
| `get_spatial_summary` | `analysis_id: UUID`, `radius_m: float` | Unified spatial report combining metrics, containment, infra, and population. |

---

## 🤖 LLM Boundary & Non-Causation Principle

The LLM is strictly used as an **orchestrator and reasoner**. It is **never trusted for**:
- Radiometric band calculations (NDVI)
- Geodesic surface area measurements
- Geographic distances or proximity radii
- Topological polygon intersections
- Validation thresholds
- Ground-truth database state

All quantitative values are computed deterministically by NumPy, Rasterio, PyProj, and PostGIS. The LLM translates user intent, coordinates tools, and formats non-causal evidence summaries.

---

## 🚀 API Reference

### 1. Agent Analysis Endpoint
**`POST /api/agent/analyze`**

**Request**:
```json
{
  "request": "Analyze vegetation change in Eastern Mau Forest between 2020 and 2025 and find nearby infrastructure within 1000m",
  "llm_provider": "gemini",
  "proximity_radius_m": 1000.0,
  "threshold": -0.20
}
```

**Response**:
```json
{
  "status": "validated",
  "aoi": "Eastern Mau Forest Reserve",
  "aoi_id": "a0000000-0000-0000-0000-000000000001",
  "analysis_id": "77caba3d-0c7e-43dc-96c9-bdd371cb1f0d",
  "analysis_period": {
    "before": "2020-01-15",
    "after": "2025-01-20"
  },
  "change": {
    "area_ha": 348.65,
    "mean_ndvi_change": -0.4215,
    "polygon_count": 3
  },
  "spatial_impact": {
    "infrastructure_count": 5,
    "population_context": {
      "population_zones_count": 2,
      "intersecting_zones_count": 1,
      "total_intersecting_population": 4200
    },
    "infrastructure": [
      {
        "name": "Nessuit Forest Ranger Station",
        "type": "Ranger Station",
        "distance_m": 0.0
      }
    ]
  },
  "validation": {
    "passed": true,
    "reasons": [
      "Both scenes verified with acceptable cloud cover (4.2% and 6.8% <= 20.0%).",
      "Verified 3 significant change polygon(s) totaling 348.65 ha (mean polygon ΔNDVI: -0.4215 <= -0.20).",
      "100% of detected change polygons are strictly contained within AOI boundary."
    ],
    "checks": [
      { "gate_name": "SCENE_RESOLVABILITY_GATE", "status": "PASSED" },
      { "gate_name": "CLOUD_COVER_GATE", "status": "PASSED" },
      { "gate_name": "RADIOMETRIC_DELTA_GATE", "status": "PASSED" },
      { "gate_name": "NOISE_SUPPRESSION_GATE", "status": "PASSED" },
      { "gate_name": "AOI_CONTAINMENT_GATE", "status": "PASSED" }
    ]
  },
  "recommended_action": "ISSUE_MONITORING_ALERT",
  "evidence": [
    "Detected 348.65 hectares of significant vegetation decrease across 3 polygon(s) in Eastern Mau Forest Reserve.",
    "Asset 'Nessuit Forest Ranger Station' (Ranger Station) directly intersects a detected change polygon (0.0 m).",
    "Detected change area directly intersects 1 population settlement zone(s) (4,200 registered residents).",
    "100% of detected polygons strictly contained within the official Area of Interest boundary."
  ],
  "orchestration_mode": "deterministic_demo",
  "reasoning_summary": "Actionable environmental event confirmed in Eastern Mau Forest Reserve: 348.65 ha of vegetation decrease detected with direct proximity/intersection to 5 infrastructure asset(s) and 1 settlement zone(s).",
  "activity_log": [
    { "step": 1, "tool": "request_parser", "status": "COMPLETED", "summary": "Parsed user request" },
    { "step": 2, "tool": "get_aoi", "status": "COMPLETED", "summary": "Resolved AOI 'Eastern Mau Forest Reserve'" },
    { "step": 3, "tool": "list_scenes", "status": "COMPLETED", "summary": "Selected scenes: Baseline -> Comparison" },
    { "step": 4, "tool": "run_ndvi_analysis", "status": "COMPLETED", "summary": "NDVI processing complete: 348.65 ha across 3 polygon(s)" },
    { "step": 5, "tool": "validate_analysis", "status": "COMPLETED", "summary": "Quality Gate Passed: 5/5 checks validated" },
    { "step": 6, "tool": "find_nearby_infrastructure", "status": "COMPLETED", "summary": "PostGIS Proximity: Found 5 infrastructure asset(s)" },
    { "step": 7, "tool": "get_population_context", "status": "COMPLETED", "summary": "Demographic Context: 4,200 residents in intersecting settlement zones" },
    { "step": 8, "tool": "decision_engine", "status": "COMPLETED", "summary": "Decision: VALIDATED -> Recommended Action: ISSUE_MONITORING_ALERT" }
  ],
  "executed_at": "2026-09-23T17:30:00.000000Z"
}
```

### 2. Agent Health Endpoint
**`GET /api/agent/health`**

**Response**:
```json
{
  "status": "online",
  "agent_layer": "TerraLens Agent Orchestrator v1.0",
  "configured_llm_provider": "gemini",
  "is_demo_mode": true,
  "registered_tools_count": 11,
  "tools": [
    "list_aois",
    "get_aoi",
    "list_scenes",
    "get_satellite_metadata",
    "run_ndvi_analysis",
    "run_ndvi_change_pipeline",
    "validate_analysis",
    "calculate_change_area",
    "find_nearby_infrastructure",
    "get_population_context",
    "analyze_population_proximity",
    "get_spatial_intersections",
    "run_spatial_intersection",
    "validate_aoi_containment",
    "get_spatial_summary"
  ],
  "database_connected": true
}
```

---

## 🧪 Automated Testing

Run the full automated test suite:

```bash
cd /Users/mikasa05/TerraLens && .venv/bin/pytest backend/tests/ -v
```

All **72 automated tests** pass across 5 test suites:
- `test_phase1.py` (8 tests): PostGIS extension, spatial tables, seed data counts, REST endpoints.
- `test_phase2_gis.py` (15 tests): Safe NDVI band algebra, NoData preservation, geodesic metric area, polygonization.
- `test_phase3_spatial.py` (19 tests): `ST_DWithin`, `ST_Distance`, `ST_Intersects`, `ST_Within` containment, demographic overlays.
- `test_phase4_agent.py` (16 tests): Tool allowlist security, parameter validation, planner generation, query resolution.
- `test_phase4_orchestrator.py` (14 tests): End-to-end natural language inquiries, cloud rejection, stable canopy handling, missing AOI/scenes resilience, and demo mode.

---

## 💻 Frontend Dashboard

Build the frontend bundle:

```bash
cd /Users/mikasa05/TerraLens/frontend && npm run build
```

Run locally:

```bash
npm run dev
```

---

## 🌍 Study Areas & Development Dataset

1. **Eastern Mau Forest Reserve (Kenya)**
   * **Coordinates**: `[35.820, -0.450]` to `[35.980, -0.320]` (EPSG:4326)
   * **Baseline Scene (2020)**: Baseline canopy simulation ($\text{Mean NDVI} \approx 0.776$).
   * **Comparison Scene (2025)**: Post-disturbance simulation ($\text{Mean NDVI} \approx 0.752$, localized decrease patches).
   * **Infrastructure**: Nessuit Forest Ranger Station, Likia Forest Outpost, Kaptunga Fire Watchtower, Njoro-Mau Narok Highway Corridor.
   * **Population Zones**: Nessuit Settlement Zone (pop: 4,200), Likia Community Area (pop: 3,100).

2. **Harz National Park (Germany)**
   * **Coordinates**: `[10.540, 51.740]` to `[10.720, 51.860]` (EPSG:4326)
   * **Baseline Scene (2019)**: Baseline spruce canopy simulation.
   * **Comparison Scene (2024)**: Bark beetle dieback patch simulation.
   * **Infrastructure**: Brocken Railway Station, Torfhaus Communications Tower, Oderteich Dam.
   * **Population Zones**: Schierke Municipality Zone (pop: 720).
