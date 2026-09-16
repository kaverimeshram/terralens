"""TerraLens Phase 2 Automated Test Suite.

Verifies:
1. NDVI formula mathematics & precision.
2. Safe zero-denominator & edge-case handling.
3. NoData sentinel preservation.
4. Physical NDVI range validation [-1.0, 1.0].
5. Temporal NDVI difference calculation (after - before).
6. Significant change threshold classification.
7. Raster GeoTIFF metadata preservation (CRS, transform, NoData, float32).
8. Raster-to-vector polygonization with Shapely & GeoJSON output.
9. Vector geometry validity & topological integrity.
10. Minimum-area noise suppression filter.
11. Geodesic metric area calculation (m² and hectares).
12. Raster grid compatibility validator (dimensions, CRS, transform).
13. End-to-end analysis service with PostGIS persistence.
14. FastAPI POST /api/analysis/ndvi-change endpoint.
15. FastAPI GET /api/analysis/{analysis_id}/changes GeoJSON endpoint.
16. FastAPI GET /api/analysis/{analysis_id} metadata endpoint.
17. FastAPI GET /api/analysis list endpoint.
18. API error handling for invalid/mismatched AOIs and scenes.
19. Stability scene comparison (Mau 2020 baseline vs 2020 stable).
"""

import uuid
from pathlib import Path
import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport
from rasterio.transform import from_bounds
from shapely.geometry import Polygon

from app.main import app
from app.database.session import async_engine
from app.gis.ndvi import (
    calculate_ndvi,
    calculate_ndvi_difference,
    detect_significant_change,
    calculate_ndvi_from_files,
    calculate_ndvi_difference_from_files,
    write_geotiff,
)
from app.gis.vectorization import (
    calculate_metric_area,
    polygonize_change_raster,
)
from app.gis.validation import (
    GISValidationError,
    validate_raster_compatibility,
    validate_ndvi_array,
    validate_geometry_validity,
)
from app.gis.analysis_service import (
    run_ndvi_change_analysis,
    resolve_raster_path,
)


# --- 1. NDVI Formula & Mathematical Accuracy ---

def test_ndvi_formula_calculation():
    """Verify NDVI formula = (NIR - Red) / (NIR + Red)."""
    red = np.array([[0.05, 0.10], [0.20, 0.02]], dtype=np.float32)
    nir = np.array([[0.50, 0.40], [0.20, 0.60]], dtype=np.float32)

    ndvi = calculate_ndvi(red, nir)

    # (0.50 - 0.05) / (0.50 + 0.05) = 0.45 / 0.55 = 0.8181818
    expected_00 = (0.50 - 0.05) / (0.50 + 0.05)
    # (0.20 - 0.20) / (0.20 + 0.20) = 0.0
    expected_10 = 0.0
    # (0.60 - 0.02) / (0.60 + 0.02) = 0.58 / 0.62 = 0.9354839
    expected_11 = (0.60 - 0.02) / (0.60 + 0.02)

    assert np.isclose(ndvi[0, 0], expected_00, atol=1e-5)
    assert np.isclose(ndvi[1, 0], expected_10, atol=1e-5)
    assert np.isclose(ndvi[1, 1], expected_11, atol=1e-5)


# --- 2. Zero Denominator & Division-by-Zero Safety ---

def test_ndvi_zero_denominator_safe():
    """Verify safe handling when Red == 0 and NIR == 0 (zero denominator)."""
    red = np.array([[0.0, 0.0], [0.1, 0.0]], dtype=np.float32)
    nir = np.array([[0.0, 0.5], [0.0, 0.0]], dtype=np.float32)

    ndvi = calculate_ndvi(red, nir)
    # Where both are 0.0, NDVI should safely evaluate to 0.0 without crash/warning
    assert ndvi[0, 0] == 0.0
    assert ndvi[1, 1] == 0.0
    assert np.all(np.isfinite(ndvi))


# --- 3. NoData Sentinel Preservation ---

def test_ndvi_nodata_preservation():
    """Verify NoData sentinel values (-9999.0) are preserved and masked."""
    nodata = -9999.0
    red = np.array([[nodata, 0.06], [0.05, nodata]], dtype=np.float32)
    nir = np.array([[0.50, nodata], [0.52, 0.50]], dtype=np.float32)

    ndvi = calculate_ndvi(red, nir, nodata=nodata)

    assert ndvi[0, 0] == nodata
    assert ndvi[0, 1] == nodata
    assert ndvi[1, 1] == nodata
    # Only [1, 0] is valid
    assert ndvi[1, 0] != nodata
    assert np.isclose(ndvi[1, 0], (0.52 - 0.05) / (0.52 + 0.05), atol=1e-5)


# --- 4. Physical NDVI Range Bounds ---

def test_ndvi_range_bounds():
    """Verify NDVI values are clamped strictly within theoretical bounds [-1.0, 1.0]."""
    red = np.array([[0.9, 0.01], [0.5, 0.0]], dtype=np.float32)
    nir = np.array([[0.1, 0.99], [0.5, 0.8]], dtype=np.float32)

    ndvi = calculate_ndvi(red, nir)
    assert np.all(ndvi >= -1.0)
    assert np.all(ndvi <= 1.0)
    assert validate_ndvi_array(ndvi) is True


# --- 5. Temporal NDVI Difference Calculation ---

def test_ndvi_difference_calculation():
    """Verify delta NDVI = after - before."""
    before = np.array([[0.80, 0.75], [0.60, -9999.0]], dtype=np.float32)
    after = np.array([[0.20, 0.85], [-9999.0, 0.50]], dtype=np.float32)

    diff = calculate_ndvi_difference(before, after, nodata=-9999.0)

    # Significant loss: 0.20 - 0.80 = -0.60
    assert np.isclose(diff[0, 0], -0.60, atol=1e-5)
    # Regrowth: 0.85 - 0.75 = +0.10
    assert np.isclose(diff[0, 1], 0.10, atol=1e-5)
    # Masked pixels remain NoData
    assert diff[1, 0] == -9999.0
    assert diff[1, 1] == -9999.0


# --- 6. Significant Change Threshold Classification ---

def test_significant_change_thresholding():
    """Verify classification categories: decrease (-1), unchanged (0), increase (+1)."""
    diff = np.array([[-0.45, -0.21], [-0.19, 0.05], [0.25, -9999.0]], dtype=np.float32)

    classified = detect_significant_change(diff, threshold=-0.20, increase_threshold=0.20)

    assert classified[0, 0] == -1  # -0.45 <= -0.20 -> decrease
    assert classified[0, 1] == -1  # -0.21 <= -0.20 -> decrease
    assert classified[1, 0] == 0   # -0.19 > -0.20 -> unchanged
    assert classified[1, 1] == 0   # 0.05 -> unchanged
    assert classified[2, 0] == 1   # 0.25 >= 0.20 -> increase
    assert classified[2, 1] == -9999  # NoData preserved


# --- 7. Raster Metadata & GeoTIFF Output Preservation ---

def test_raster_metadata_preservation(tmp_path):
    """Verify output GeoTIFF preserves CRS, transform, dimensions, and NoData."""
    bounds = (35.82, -0.45, 35.98, -0.32)
    width, height = 50, 50
    transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], width, height)
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "nodata": -9999.0,
        "width": width,
        "height": height,
        "count": 1,
        "crs": "EPSG:4326",
        "transform": transform,
    }

    dummy_data = np.full((height, width), 0.75, dtype=np.float32)
    out_file = tmp_path / "test_out.tif"
    write_geotiff(out_file, dummy_data, profile)

    import rasterio
    with rasterio.open(out_file) as src:
        assert src.crs.to_string() == "EPSG:4326"
        assert src.width == 50
        assert src.height == 50
        assert src.dtypes[0] == "float32"
        assert src.nodata == -9999.0
        assert np.allclose(src.bounds, bounds)


# --- 8. Geodesic Metric Area Calculation ---

def test_geodesic_metric_area_calculation():
    """Verify geodesic metric area calculates true surface area in m² and hectares."""
    # Create 0.01 deg x 0.01 deg box near equator (~1.11 km x 1.11 km ~ 1.23 km² = 123 ha = 1,230,000 m²)
    box_poly = Polygon([(35.0, 0.0), (35.01, 0.0), (35.01, 0.01), (35.0, 0.01), (35.0, 0.0)])
    area_m2, area_ha = calculate_metric_area(box_poly, crs_str="EPSG:4326")

    # Raw degree area is 0.0001 deg² - metric area should be ~1,230,000 m²
    assert area_m2 > 1_000_000, f"Expected > 1,000,000 m², got {area_m2}"
    assert area_ha > 100, f"Expected > 100 ha, got {area_ha}"
    assert np.isclose(area_ha, area_m2 / 10000.0, atol=1e-3)


# --- 9. Raster-to-Vector Polygonization & Noise Filtering ---

def test_raster_to_polygon_conversion_and_filtering():
    """Verify raster polygonization extracts clean polygons and filters small noise."""
    bounds = (35.82, -0.45, 35.98, -0.32)
    width, height = 100, 100
    transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], width, height)

    # Create change mask with:
    # 1. A large 20x20 block (significant change)
    # 2. A tiny 1-pixel noise point
    change_mask = np.zeros((height, width), dtype=np.int16)
    change_mask[20:40, 20:40] = -1  # 400 pixels (~large area)
    change_mask[80, 80] = -1        # 1 pixel (~single-pixel noise)

    ndvi_diff = np.full((height, width), -0.05, dtype=np.float32)
    ndvi_diff[20:40, 20:40] = -0.55
    ndvi_diff[80, 80] = -0.30

    features = polygonize_change_raster(
        change_mask=change_mask,
        ndvi_difference=ndvi_diff,
        transform=transform,
        crs_str="EPSG:4326",
        min_area_m2=50000.0,  # 50,000 m² threshold (1 pixel is ~25,602 m², 400 pixels is ~10.24M m²)
        target_value=-1,
    )

    # Only the 400-pixel cluster (> 10M m²) survives the 50,000 m² filter; 1-pixel noise (25,602 m²) is eliminated
    assert len(features) == 1
    poly_feat = features[0]
    assert poly_feat["properties"]["area_m2"] > 1_000_000.0
    assert poly_feat["properties"]["mean_ndvi_change"] < -0.50
    assert poly_feat["properties"]["change_type"] == "detected vegetation decrease"


# --- 10. Vector Geometry Validity ---

def test_vector_geometry_validity():
    """Verify extracted geometries are valid Shapely polygons."""
    bounds = (35.82, -0.45, 35.98, -0.32)
    transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], 50, 50)
    mask = np.zeros((50, 50), dtype=np.int16)
    mask[10:25, 10:25] = -1
    diff = np.full((50, 50), -0.40, dtype=np.float32)

    features = polygonize_change_raster(mask, diff, transform=transform, min_area_m2=100.0)
    assert len(features) > 0
    for f in features:
        geom = f["shapely_geom"]
        assert geom.is_valid
        assert validate_geometry_validity(geom, min_area_m2=100.0, area_m2=f["properties"]["area_m2"])


# --- 11. Raster Compatibility Validator ---

def test_raster_compatibility_validation():
    """Verify validator catches raster dimension and CRS mismatches."""
    # Test valid files
    red_p = resolve_raster_path("backend/data/imagery/mau_forest_2020_b04.tif")
    nir_p = resolve_raster_path("backend/data/imagery/mau_forest_2020_b08.tif")
    p1, p2 = validate_raster_compatibility(red_p, nir_p)
    assert p1["crs"] == p2["crs"]
    assert p1["width"] == p2["width"]

    # Test mismatched files (Mau vs Harz)
    harz_p = resolve_raster_path("backend/data/imagery/harz_2019_b04.tif")
    with pytest.raises(GISValidationError):
        validate_raster_compatibility(red_p, harz_p)


# --- 12. Full Mau Forest 2020 -> 2025 Analysis Execution ---

@pytest.mark.asyncio
async def test_mau_forest_full_pipeline():
    """Verify complete end-to-end Mau Forest 2020 -> 2025 analysis with PostGIS persistence."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Get AOI
        aoi_res = await ac.get("/api/aois?format=json")
        assert aoi_res.status_code == 200
        aois = aoi_res.json()["aois"]
        mau_aoi = next(a for a in aois if "Mau" in a["name"])
        aoi_id = mau_aoi["id"]

        # Get Scenes
        scenes_res = await ac.get(f"/api/aois/{aoi_id}/scenes")
        assert scenes_res.status_code == 200
        scenes = scenes_res.json()["scenes"]

        scene_2020 = next(s for s in scenes if "20200115" in s["scene_identifier"])
        scene_2025 = next(s for s in scenes if "20250120" in s["scene_identifier"])

        payload = {
            "aoi_id": aoi_id,
            "before_scene_id": scene_2020["id"],
            "after_scene_id": scene_2025["id"],
            "threshold": -0.20,
            "minimum_area_m2": 500.0,
        }

        analysis_res = await ac.post("/api/analysis/ndvi-change", json=payload)
        assert analysis_res.status_code == 200
        data = analysis_res.json()

        assert data["status"] == "COMPLETED"
        assert "analysis_id" in data
        metrics = data["metrics"]
        assert metrics["mean_before_ndvi"] > 0.70
        assert metrics["mean_after_ndvi"] > 0.70
        assert metrics["mean_ndvi_difference"] < 0.0
        assert metrics["changed_pixels_count"] > 5000
        assert metrics["change_polygon_count"] > 0
        assert metrics["total_change_area_ha"] > 100.0

        # Verify GeoJSON output endpoint
        analysis_id = data["analysis_id"]
        changes_res = await ac.get(f"/api/analysis/{analysis_id}/changes")
        assert changes_res.status_code == 200
        geojson_data = changes_res.json()
        assert geojson_data["type"] == "FeatureCollection"
        assert len(geojson_data["features"]) == metrics["change_polygon_count"]

        first_poly = geojson_data["features"][0]
        assert "properties" in first_poly
        assert "area_m2" in first_poly["properties"]
        assert "area_ha" in first_poly["properties"]
        assert first_poly["properties"]["change_type"] == "detected vegetation decrease"


# --- 13. Stability Scene Test (No Significant Change) ---

@pytest.mark.asyncio
async def test_stable_scene_no_change():
    """Verify stable comparison (Mau 2020 baseline vs 2020 stable) produces zero significant decrease polygons."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        aoi_res = await ac.get("/api/aois?format=json")
        aois = aoi_res.json()["aois"]
        mau_aoi = next(a for a in aois if "Mau" in a["name"])
        aoi_id = mau_aoi["id"]

        scenes_res = await ac.get(f"/api/aois/{aoi_id}/scenes")
        scenes = scenes_res.json()["scenes"]

        scene_baseline = next(s for s in scenes if "20200115" in s["scene_identifier"])
        scene_stable = next(s for s in scenes if "STABLE" in s["scene_identifier"])

        payload = {
            "aoi_id": aoi_id,
            "before_scene_id": scene_baseline["id"],
            "after_scene_id": scene_stable["id"],
            "threshold": -0.20,
            "minimum_area_m2": 500.0,
        }

        res = await ac.post("/api/analysis/ndvi-change", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["metrics"]["changed_pixels_count"] == 0
        assert data["metrics"]["change_polygon_count"] == 0
        assert data["metrics"]["total_change_area_m2"] == 0.0


# --- 14. API Error Handling & Validation Tests ---

@pytest.mark.asyncio
async def test_api_validation_errors():
    """Verify API returns 400 Bad Request when AOI and scenes do not match."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Random non-existent UUIDs
        fake_id = str(uuid.uuid4())
        payload = {
            "aoi_id": fake_id,
            "before_scene_id": fake_id,
            "after_scene_id": fake_id,
        }
        res = await ac.post("/api/analysis/ndvi-change", json=payload)
        assert res.status_code in (400, 404)


# --- 15. Analysis List & Metadata Endpoints ---

@pytest.mark.asyncio
async def test_api_analysis_list_and_detail():
    """Verify GET /api/analysis and GET /api/analysis/{id} endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        list_res = await ac.get("/api/analysis")
        assert list_res.status_code == 200
        data = list_res.json()
        assert "analysis_runs" in data
        assert len(data["analysis_runs"]) > 0

        first_id = data["analysis_runs"][0]["id"]
        detail_res = await ac.get(f"/api/analysis/{first_id}")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["id"] == first_id
        assert "aoi_name" in detail_data
        assert "before_scene" in detail_data
        assert "after_scene" in detail_data
