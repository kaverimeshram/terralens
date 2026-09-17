# TerraLens

### AI-Powered Satellite & Spatial Intelligence Agent

TerraLens is an intelligent geospatial agent that converts natural-language remote sensing and geographic inquiries into real GIS analysis workflows, deterministic raster algebra calculations, PostGIS spatial queries, and interactive visual mapping.

---

## 🛰️ Core Capabilities

- **Natural Language Remote Sensing**: Translates complex spatial inquiries (e.g. *"Show me where vegetation decreased significantly between 2020 and 2025 and identify nearby infrastructure"*) into multi-step GIS analysis pipelines.
- **Deterministic GIS Processing**: Uses NumPy, Rasterio, and GeoPandas for radiometric index calculations (NDVI, NDVI Difference, Thresholding, Raster-to-Vector) rather than imprecise LLM approximations.
- **PostGIS Spatial Database**: Real spatial operations (`ST_DWithin`, `ST_Intersects`, `ST_Area`, `ST_Distance`, `ST_Within`, `ST_AsGeoJSON`) on polygon boundaries, population zones, and infrastructure layers with spatial GIST indexing.
- **Rigorous Validation Gate**: Enforces physical and remote sensing quality gates (cloud cover thresholds, minimum NDVI delta, minimum change area, geometry validity) before accepting results.
- **Concise Activity Logging**: Transparent user-facing execution log without exposing raw LLM internal thoughts.
- **Interactive Intelligence Map**: High-performance MapLibre GL UI with vector polygon statistics, infrastructure popups, and proximity overlays.

---

## 🏛️ Architecture & Project Structure

```
terralens/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entrypoint & router mounts
│   │   ├── config.py                  # Pydantic environment configuration
│   │   ├── api/                       # REST API route handlers
│   │   │   ├── health.py              # Healthcheck & PostGIS connection status
│   │   │   ├── aois.py                # AOI retrieval & GeoJSON boundaries
│   │   │   ├── scenes.py              # Satellite scene catalog & metadata
│   │   │   ├── infrastructure.py      # Spatial queries & ST_DWithin search
│   │   │   └── analysis.py            # Phase 2 & 3: NDVI change & PostGIS spatial analysis
│   │   ├── database/                  # Async & sync SQLAlchemy sessions
│   │   ├── models/                    # GeoAlchemy2 & SQLAlchemy models
│   │   ├── gis/                       # Deterministic GIS & PostGIS spatial engine
│   │   │   ├── ndvi.py                # Safe vectorized NDVI & temporal delta math
│   │   │   ├── vectorization.py       # Raster-to-vector & geodesic metric areas
│   │   │   ├── validation.py          # Grid compatibility & remote sensing gates
│   │   │   ├── spatial_service.py     # Phase 3: PostGIS Spatial Intelligence Service
│   │   │   └── analysis_service.py    # Pipeline orchestrator & PostGIS persistence
│   │   ├── agents/                    # LLM Tool-calling orchestrator (Phase 4)
│   │   └── validation/                # Quality validation gate (Phase 4)
│   ├── data/
│   │   ├── imagery/                   # Multispectral GeoTIFFs (B04, B08, B11)
│   │   ├── outputs/                   # Generated analysis GeoTIFFs (gitignored)
│   │   └── seed/                      # Documented study areas & infrastructure
│   ├── migrations/
│   │   └── schema.sql                 # PostGIS SQL schema & GIST spatial indexes
│   ├── scripts/
│   │   ├── seed_db.py                 # Database initializer and seeder
│   │   └── generate_sample_imagery.py # Georeferenced GeoTIFF generator
│   ├── tests/
│   │   ├── test_phase1.py             # Phase 1 foundation test suite
│   │   ├── test_phase2_gis.py         # Phase 2 deterministic GIS test suite
│   │   └── test_phase3_spatial.py     # Phase 3 PostGIS spatial engine test suite
│   └── requirements.txt
├── frontend/                          # React + Vite + TypeScript + MapLibre GL
├── .env.example
├── .env
└── README.md
```

---

## 🗺️ Phase 3: PostGIS Spatial Intelligence Engine

Phase 3 connects the vectorized vegetation-change polygons generated in Phase 2 to real-world infrastructure, population zones, and study area boundaries using **PostgreSQL + PostGIS** spatial intelligence.

All proximity queries, geometric intersections, containment validations, and spatial aggregations are computed directly inside PostGIS using spatial SQL, **never using Euclidean math in Python or LLM guessing**.

```text
NDVI Change Detection (Phase 2)
        ↓
Change Polygons (PostGIS MultiPolygons)
        ↓
PostGIS Spatial Analysis (ST_DWithin, ST_Distance, ST_Intersects)
        ↓
Infrastructure / Population / AOI Relationships
        ↓
Spatial Intelligence Results & GeoJSON API
        ↓
Interactive MapLibre GL Frontend
```

---

### 🎓 Academic DBMS & Spatial Database Concepts

TerraLens is designed to demonstrate core Spatial Database Management System (SDBMS) principles:

#### 1. Geometry vs. Geography & Geodesic Distance
- **Geometry (`GEOMETRY(MultiPolygon, 4326)`)**: Stores coordinates in angular degrees on the WGS84 ellipsoid.
- **Geography (`geometry::geography`)**: Automatically projects spherical coordinates onto the WGS84 great-circle spheroid, enabling exact metric distance queries (`ST_Distance` and `ST_DWithin`) in meters without requiring local projected coordinate systems (UTM).

#### 2. Spatial Indexing (GIST R-Trees)
All spatial tables (`aois`, `satellite_scenes`, `change_polygons`, `infrastructure`, `population_zones`) feature Generalized Search Tree (GiST) R-tree spatial indexes:
```sql
CREATE INDEX idx_change_polygons_geom ON change_polygons USING GIST (geometry);
CREATE INDEX idx_infrastructure_geom ON infrastructure USING GIST (geometry);
CREATE INDEX idx_population_zones_geom ON population_zones USING GIST (geometry);
```
These indexes provide $O(\log N)$ bounding-box filtering, preventing costly full table scans when executing spatial joins and proximity queries.

#### 3. Spatial Predicates & Operators
- **`ST_DWithin(geom1::geography, geom2::geography, radius_m)`**: Index-accelerated spatial proximity test. Returns `true` if two geometries are within the specified geodesic distance in meters.
- **`ST_Distance(geom1::geography, geom2::geography)`**: Computes the minimum ellipsoidal distance in meters between any point in geometry 1 and any point in geometry 2.
- **`ST_Intersects(geom1, geom2)`**: Evaluates whether two spatial geometries share any common points (point, line, or area).
- **`ST_Within(geom1, geom2)`**: Topological containment predicate verifying that geometry 1 is entirely inside geometry 2.
- **`ST_Intersection(geom1, geom2)`**: Computes the exact geometric overlap/shared shape between intersecting polygons.

#### 4. Spatial Joins & Window Ranking
TerraLens finds distinct closest infrastructure assets using PostGIS spatial joins combined with SQL window functions:
```sql
WITH ranked_matches AS (
    SELECT 
        i.id as infrastructure_id,
        i.name,
        i.type,
        ST_AsGeoJSON(i.geometry) as geojson_geom,
        cp.id as nearest_change_polygon_id,
        cp.area_m2 as change_polygon_area_m2,
        ST_Distance(i.geometry::geography, cp.geometry::geography) as distance_m,
        ROW_NUMBER() OVER (
            PARTITION BY i.id 
            ORDER BY ST_Distance(i.geometry::geography, cp.geometry::geography) ASC
        ) as rank_num
    FROM infrastructure i
    JOIN change_polygons cp ON cp.analysis_run_id = :analysis_id
    WHERE ST_DWithin(i.geometry::geography, cp.geometry::geography, :radius_m)
)
SELECT * FROM ranked_matches WHERE rank_num = 1 ORDER BY distance_m ASC;
```

#### 5. Spatial Aggregation
- **`ST_Area(geometry::geography)`**: Geodesic ellipsoidal area in $m^2$.
- **`SUM(area_m2)` / `COUNT(id)` / `AVG(change_value)`**: Database-level aggregation across all detected change polygons in an analysis run.

#### 6. Factual Proximity & Non-Causation Boundary
Proximity outputs maintain strict scientific objectivity:
- Factual: *"A primary highway corridor is within 620 m of a detected vegetation-change polygon."*
- Prohibited: *"The highway caused the vegetation loss."*

---

## 🌿 Phase 2: Deterministic GIS & Remote Sensing Engine

### 1. Remote Sensing Fundamentals & Spectral Bands

Vegetation index calculations rely on multispectral surface reflectance:
* **Band 4 (B04 - Visible Red, central $\lambda \approx 665\text{ nm}$)**: Strongly absorbed by chlorophyll in photosynthetic plant tissue.
* **Band 8 (B08 - Near-Infrared / NIR, central $\lambda \approx 842\text{ nm}$)**: Highly reflected and scattered by healthy leaf mesophyll cell structures.
* **Band 11 (B11 - Shortwave-Infrared-1 / SWIR-1, central $\lambda \approx 1610\text{ nm}$)**: Sensitive to canopy water content and soil exposure.

### 2. NDVI & Temporal Change Formulation

$$\text{NDVI} = \frac{\text{NIR} - \text{Red}}{\text{NIR} + \text{Red}} = \frac{\text{B08} - \text{B04}}{\text{B08} + \text{B04}}$$

$$\Delta\text{NDVI} = \text{NDVI}_{\text{after}} - \text{NDVI}_{\text{before}}$$

* **Division-by-Zero Protection**: Handles zero reflectance $(\text{NIR} + \text{Red} \le 0)$ safely by returning $0.0$, preserving physical bounds $[-1.0, 1.0]$.
* **NoData Handling**: Preserves NoData values ($-9999.0$) across all matrix algebra operations without fabricating replacement data.

### 3. Vegetation Change Thresholding & Nomenclature

Pixels are classified into deterministic change categories:
* **Detected Vegetation Decrease / Potential Vegetation Loss**: $\Delta\text{NDVI} \le -0.20$ (default threshold). Denotes canopy reduction, disturbance, or clearing.
* **Detected Vegetation Increase / Regrowth**: $\Delta\text{NDVI} \ge +0.20$.
* **Unchanged / Stable Canopy**: $-0.20 < \Delta\text{NDVI} < +0.20$.

> **Note on Terminology**: Outputs use objective remote sensing terminology (*"detected vegetation decrease"*, *"potential vegetation loss"*, and *"significant vegetation change"*) rather than unverified legal claims like "confirmed deforestation."

### 4. Raster-to-Vector & Geodesic Metric Area Calculations

* **Polygonization**: Vectorizes raster change masks into clean GIS polygons using `rasterio.features.shapes` and Shapely geometry validation.
* **Geodesic Metric Surface Area**: Rasters in `EPSG:4326` have non-square degree pixels ($\sim 44.5\,\text{m} \times 36.2\,\text{m}$ for Mau Forest). The engine computes exact ellipsoidal geodesic area ($m^2$ and hectares) using `pyproj.Geod(ellps="WGS84")` and PostGIS `ST_Area(geometry::geography)`, **never assuming hardcoded $10\,\text{m} \times 10\,\text{m} = 100\,\text{m}^2$ pixel areas**.
* **Noise Suppression**: Discards sub-threshold isolated noise polygons smaller than `min_area_m2` (default $500\,\text{m}^2$).
* **Zonal Statistics**: Extracts polygon-level `mean_ndvi_change`, `mean_before_ndvi`, and `mean_after_ndvi`.

---

## 🌍 Study Areas & Development Dataset

> [!NOTE]
> **Dataset Provenance Disclaimer**:
> The current development imagery is synthetic Sentinel-2-like remote-sensing simulation data used for deterministic pipeline development and testing. It is not raw satellite imagery.

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

---

## 🚀 API Endpoints

### Phase 3: PostGIS Spatial Intelligence & Proximity
* **Nearby Infrastructure Query**: `GET /api/analysis/{analysis_id}/nearby-infrastructure?radius_m=1000` (format: `json` or `geojson`)
  ```json
  {
    "analysis_id": "77caba3d-0c7e-43dc-96c9-bdd371cb1f0d",
    "radius_m": 1000.0,
    "infrastructure_count": 5,
    "associated_change_area_ha": 348.65,
    "infrastructure": [
      {
        "id": "c0000000-0000-0000-0000-000000000001",
        "name": "Nessuit Forest Ranger Station",
        "type": "Ranger Station",
        "distance_m": 0.0,
        "nearest_change_polygon_id": "249e1f67-82a8-48fd-a716-99fd49dae592",
        "change_polygon_area_m2": 2185600.0
      }
    ],
    "factual_summary": [
      "5 infrastructure asset(s) located within 1000 m of detected vegetation-change polygons.",
      "'Nessuit Forest Ranger Station' (Ranger Station) directly intersects a detected vegetation-change polygon."
    ]
  }
  ```
* **Unified Spatial Summary**: `GET /api/analysis/{analysis_id}/spatial-summary?radius_m=1000`
* **Population Zone Demographic Proximity**: `GET /api/analysis/{analysis_id}/population-context?radius_m=1000`
* **Exact Geometric Intersection**: `GET /api/analysis/{analysis_id}/spatial-intersection?layer=infrastructure`
* **AOI Containment Validation**: `GET /api/analysis/{analysis_id}/aoi-containment`

### Phase 2: NDVI Change Analysis & Vector Retrieval
* **Execute Analysis**: `POST /api/analysis/ndvi-change`
* **Retrieve GeoJSON Change Polygons**: `GET /api/analysis/{analysis_id}/changes`
* **Get Analysis Run Metadata**: `GET /api/analysis/{analysis_id}`
* **List Past Analysis Runs**: `GET /api/analysis`

### Phase 1: Exploration & Spatial Queries
* **Health & PostGIS Status**: `GET /api/health`
* **AOIs GeoJSON**: `GET /api/aois?format=geojson`
* **AOI Scenes**: `GET /api/aois/{aoi_id}/scenes`
* **Coordinate Proximity**: `GET /api/infrastructure/nearby?lon=35.885&lat=-0.382&radius_meters=5000`

---

## 🤖 AI Boundary & Architectural Principle

Phase 3 is entirely **deterministic and database-driven**.

The eventual architecture in Phase 4 is:
```text
User Natural Language Inquiry
        ↓
AI Tool-Calling Agent
        ↓
Deterministic GIS & PostGIS Tool Execution
        ↓
Verified Database Results & Quality Gate
        ↓
Factual AI Synthesis & Explanation
```

The AI agent does not fabricate spatial relationships; it selects and orchestrates deterministic GIS and PostGIS functions.

---

## 🧪 Testing

```bash
# Run full automated test suite (Phase 1, Phase 2, and Phase 3)
.venv/bin/pytest backend/tests/ -v
```

All **42 automated tests** verify:
- PostGIS extensions, tables, spatial indexes, and connections
- NDVI formulas, NoData handling, and physical bounds $[-1.0, 1.0]$
- Geodesic metric area calculation ($m^2$ and ha)
- Raster-to-vector polygonization and geometry validity
- PostGIS `ST_DWithin` and `ST_Distance` proximity queries
- PostGIS `ST_Intersects` and `ST_Intersection` layer overlays
- PostGIS `ST_Within` AOI topological containment validation
- Empty radius and out-of-range zero result handling
- All FastAPI REST endpoints and error conditions
- End-to-end Eastern Mau Forest 2020 $\to$ 2025 demonstration scenario.
