# TerraLens

### AI-Powered Satellite & Spatial Intelligence Agent

TerraLens is an intelligent geospatial agent that converts natural-language remote sensing and geographic inquiries into real GIS analysis workflows, deterministic raster algebra calculations, PostGIS spatial queries, and interactive visual mapping.

---

## 🛰️ Core Capabilities

- **Natural Language Remote Sensing**: Translates complex spatial inquiries (e.g. *"Show me where vegetation decreased significantly between 2020 and 2025 and identify nearby infrastructure"*) into multi-step GIS analysis pipelines.
- **Deterministic GIS Processing**: Uses NumPy, Rasterio, and GeoPandas for radiometric index calculations (NDVI, NDVI Difference, Thresholding, Raster-to-Vector) rather than imprecise LLM approximations.
- **PostGIS Spatial Database**: Real spatial operations (`ST_DWithin`, `ST_Intersects`, `ST_Area`, `ST_Distance`, `ST_AsGeoJSON`) on polygon boundaries and infrastructure layers with spatial GIST indexing.
- **Rigorous Validation Gate**: Enforces physical and remote sensing quality gates (cloud cover thresholds, minimum NDVI delta, minimum change area, geometry validity) before accepting results.
- **Concise Activity Logging**: Transparent user-facing execution log without exposing raw LLM internal thoughts.
- **Interactive Intelligence Map**: High-performance MapLibre GL UI with satellite layer toggling, vector polygon statistics, and proximity overlays.

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
│   │   │   └── analysis.py            # Phase 2: NDVI change analysis & GeoJSON polygons
│   │   ├── database/                  # Async & sync SQLAlchemy sessions
│   │   ├── models/                    # GeoAlchemy2 & SQLAlchemy models
│   │   ├── gis/                       # Phase 2: Deterministic GIS & remote sensing engine
│   │   │   ├── ndvi.py                # Safe vectorized NDVI & temporal delta math
│   │   │   ├── vectorization.py       # Raster-to-vector & geodesic metric areas
│   │   │   ├── validation.py          # Grid compatibility & remote sensing gates
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
│   │   └── test_phase2_gis.py         # Phase 2 deterministic GIS test suite
│   └── requirements.txt
├── frontend/                          # React + Vite + TypeScript + MapLibre GL
├── .env.example
├── .env
└── README.md
```

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

2. **Harz National Park (Germany)**
   * **Coordinates**: `[10.540, 51.740]` to `[10.720, 51.860]` (EPSG:4326)
   * **Baseline Scene (2019)**: Baseline spruce canopy simulation.
   * **Comparison Scene (2024)**: Bark beetle dieback patch simulation.

---

## 🚀 API Endpoints

### Phase 2: NDVI Change Analysis & Vector Retrieval
* **Execute Analysis**: `POST /api/analysis/ndvi-change`
  ```json
  {
    "aoi_id": "a0000000-0000-0000-0000-000000000001",
    "before_scene_id": "b0000000-0000-0000-0000-000000000001",
    "after_scene_id": "b0000000-0000-0000-0000-000000000002",
    "threshold": -0.20,
    "minimum_area_m2": 500.0
  }
  ```
* **Retrieve GeoJSON Change Polygons**: `GET /api/analysis/{analysis_id}/changes`
* **Get Analysis Run Metadata**: `GET /api/analysis/{analysis_id}`
* **List Past Analysis Runs**: `GET /api/analysis`

### Phase 1: Exploration & Spatial Queries
* **Health & PostGIS Status**: `GET /api/health`
* **AOIs GeoJSON**: `GET /api/aois?format=geojson`
* **AOI Scenes**: `GET /api/aois/{aoi_id}/scenes`
* **Nearby Infrastructure**: `GET /api/infrastructure/nearby?lon=35.885&lat=-0.382&radius_meters=5000`

---

## 🧪 Testing

```bash
# Run full automated test suite (Phase 1 + Phase 2)
.venv/bin/pytest backend/tests/ -v
```
All 23 automated tests verify database integrity, spatial operations, NDVI math, polygonization, geodesic areas, and live API endpoints.
