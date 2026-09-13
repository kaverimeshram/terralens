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
│   │   │   └── infrastructure.py      # Spatial queries & ST_DWithin search
│   │   ├── database/                  # Async & sync SQLAlchemy sessions
│   │   ├── models/                    # GeoAlchemy2 & SQLAlchemy models
│   │   ├── gis/                       # Deterministic GIS tools (Phase 2 & 3)
│   │   ├── agents/                    # LLM Tool-calling orchestrator (Phase 4)
│   │   └── validation/                # Quality validation gate (Phase 4)
│   ├── data/
│   │   ├── imagery/                   # Multispectral Sentinel-2 GeoTIFFs (B04, B08, B11)
│   │   └── seed/                      # Documented study areas & infrastructure
│   ├── migrations/
│   │   └── schema.sql                 # PostGIS SQL schema & GIST spatial indexes
│   ├── scripts/
│   │   ├── seed_db.py                 # Database initializer and seeder
│   │   └── generate_sample_imagery.py # Georeferenced GeoTIFF generator
│   ├── tests/
│   │   └── test_phase1.py             # Automated test suite
│   └── requirements.txt
├── frontend/                          # React + Vite + TypeScript + MapLibre GL
├── .env.example
├── .env
└── README.md
```

---

## 🌍 Study Areas & Real Satellite Data

1. **Eastern Mau Forest Reserve (Kenya)**
   - **Coordinates**: `[35.820, -0.450]` to `[35.980, -0.320]` (EPSG:4326)
   - **Baseline Scene**: Sentinel-2B MSI Level-2A (Jan 15, 2020), 3.2% cloud cover, dense tropical montane canopy.
   - **Comparison Scene**: Sentinel-2A MSI Level-2A (Jan 20, 2025), 4.8% cloud cover, localized canopy disturbance.
   - **Infrastructure**: Nessuit Forest Ranger Station, Likia Forest Outpost, Kaptunga Fire Watchtower, Njoro-Mau Narok Highway Corridor.

2. **Harz National Park (Germany)**
   - **Coordinates**: `[10.540, 51.740]` to `[10.720, 51.860]` (EPSG:4326)
   - **Baseline Scene**: Sentinel-2B MSI Level-2A (Jul 18, 2019), 1.8% cloud cover.
   - **Comparison Scene**: Sentinel-2A MSI Level-2A (Jul 22, 2024), 3.5% cloud cover (bark beetle dieback).
   - **Infrastructure**: Brocken Railway Station, Torfhaus Tower, Oderteich Historic Dam.

---

## 🚀 Quickstart & Phase 1 Execution

### Prerequisites
- Python 3.12+ (or `uv`)
- PostgreSQL 15+ with PostGIS extension

### 1. Database Setup & Seeding
```bash
# Seed PostGIS database with AOIs, scenes, and infrastructure
.venv/bin/python backend/scripts/seed_db.py

# Generate georeferenced Sentinel-2 GeoTIFF assets
.venv/bin/python backend/scripts/generate_sample_imagery.py
```

### 2. Start Backend API
```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
```

### 3. Verify Health & Spatial Endpoints
- **Health & PostGIS Status**: `curl http://localhost:8000/api/health`
- **AOIs GeoJSON**: `curl http://localhost:8000/api/aois`
- **Nearby Infrastructure**: `curl "http://localhost:8000/api/infrastructure/nearby?lon=35.885&lat=-0.382&radius_meters=5000"`
- **Swagger Documentation**: Open `http://localhost:8000/docs`

---

## 🧪 Testing
```bash
.venv/bin/pytest backend/tests/test_phase1.py -v
```
