"""TerraLens Vectorization & Geodesic Area Calculation Engine.

Converts significant-change raster masks into valid GIS vector polygons,
computes true geodesic metric areas (m² and hectares) without assuming flat 10m pixels,
extracts zonal statistics, and filters out sub-threshold noise.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pyproj
from rasterio.features import geometry_mask, shapes
from rasterio.transform import Affine
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.validation import make_valid

# WGS84 Geodetic reference for exact ellipsoidal geodesic surface area calculations
WGS84_GEOD = pyproj.Geod(ellps="WGS84")


def calculate_metric_area(
    geom: Union[Polygon, MultiPolygon],
    crs_str: str = "EPSG:4326",
) -> Tuple[float, float]:
    """Calculate true metric surface area in square meters (m²) and hectares (ha).

    Handles geographic CRS (e.g. EPSG:4326) using geodesic ellipsoidal geometry,
    avoiding any assumption of square or 10m pixels.

    Parameters
    ----------
    geom : Polygon or MultiPolygon
        Shapely geometry.
    crs_str : str
        Coordinate Reference System string (default: 'EPSG:4326').

    Returns
    -------
    Tuple[float, float]
        (area_m2, area_ha)
    """
    if geom.is_empty:
        return 0.0, 0.0

    # If geographic coordinates (WGS84), use geodesic ellipsoidal calculation
    if "4326" in crs_str or "WGS84" in crs_str.upper() or "CRS84" in crs_str.upper():
        area_m2, _ = WGS84_GEOD.geometry_area_perimeter(geom)
        area_m2 = abs(float(area_m2))
    else:
        # If already in a metric projected coordinate system (e.g. UTM)
        area_m2 = abs(float(geom.area))

    area_ha = area_m2 / 10000.0
    return round(area_m2, 2), round(area_ha, 4)


def extract_zonal_stats(
    geom: Union[Polygon, MultiPolygon],
    raster_array: np.ndarray,
    transform: Affine,
    nodata: float = -9999.0,
) -> float:
    """Compute mean pixel value of raster_array within the polygon boundary using geometry_mask."""
    try:
        mask = geometry_mask(
            [mapping(geom)],
            out_shape=raster_array.shape,
            transform=transform,
            invert=True,  # True inside the geometry
        )
        valid_mask = mask & (raster_array != nodata) & np.isfinite(raster_array)
        valid_pixels = raster_array[valid_mask]
        if len(valid_pixels) > 0:
            return float(np.mean(valid_pixels))
    except Exception:
        pass

    return 0.0


def polygonize_change_raster(
    change_mask: np.ndarray,
    ndvi_difference: np.ndarray,
    before_ndvi: Optional[np.ndarray] = None,
    after_ndvi: Optional[np.ndarray] = None,
    transform: Affine = Affine.identity(),
    crs_str: str = "EPSG:4326",
    min_area_m2: float = 500.0,
    target_value: int = -1,
    change_type_label: str = "detected vegetation decrease",
) -> List[Dict[str, Any]]:
    """Convert classified change raster into filtered, valid GIS polygons with metric attributes.

    Parameters
    ----------
    change_mask : np.ndarray
        Classified raster array where target_value (e.g. -1) marks significant change.
    ndvi_difference : np.ndarray
        Continuous NDVI difference array (after - before).
    before_ndvi : np.ndarray, optional
        Baseline NDVI array.
    after_ndvi : np.ndarray, optional
        Comparison NDVI array.
    transform : Affine
        Affine geotransform of the raster.
    crs_str : str
        CRS string (default: "EPSG:4326").
    min_area_m2 : float
        Minimum polygon area threshold in square meters to eliminate single-pixel noise.
    target_value : int
        Pixel value to vectorize (default: -1 for decrease).
    change_type_label : str
        Human-readable change type description.

    Returns
    -------
    List[Dict[str, Any]]
        List of feature dictionaries containing 'geometry' (GeoJSON), 'shapely_geom',
        and 'properties' (area_m2, area_ha, mean_ndvi_change, change_type, etc.).
    """
    # Binary mask for target class
    binary_mask = (change_mask == target_value).astype(np.uint8)

    if not np.any(binary_mask):
        return []

    # Extract polygon geometries using rasterio shapes
    extracted_shapes = shapes(
        binary_mask,
        mask=(binary_mask == 1),
        transform=transform,
        connectivity=8,
    )

    features = []

    for geom_dict, val in extracted_shapes:
        if val != 1:
            continue

        raw_geom = shape(geom_dict)
        # Ensure geometry is valid
        if not raw_geom.is_valid:
            valid_geom = make_valid(raw_geom)
        else:
            valid_geom = raw_geom

        if valid_geom.is_empty:
            continue

        # Decompose collections if any
        geoms_to_process = []
        if valid_geom.geom_type in ("Polygon", "MultiPolygon"):
            geoms_to_process.append(valid_geom)
        elif valid_geom.geom_type == "GeometryCollection":
            for g in valid_geom.geoms:
                if g.geom_type in ("Polygon", "MultiPolygon"):
                    geoms_to_process.append(g)

        for poly in geoms_to_process:
            area_m2, area_ha = calculate_metric_area(poly, crs_str=crs_str)

            # Filter out tiny noise polygons below min_area_m2
            if area_m2 < min_area_m2:
                continue

            # Calculate zonal statistics for this specific polygon
            mean_diff = extract_zonal_stats(poly, ndvi_difference, transform)
            mean_before = (
                extract_zonal_stats(poly, before_ndvi, transform)
                if before_ndvi is not None
                else None
            )
            mean_after = (
                extract_zonal_stats(poly, after_ndvi, transform)
                if after_ndvi is not None
                else None
            )

            feature = {
                "type": "Feature",
                "geometry": mapping(poly),
                "shapely_geom": poly,
                "properties": {
                    "change_type": change_type_label,
                    "area_m2": area_m2,
                    "area_ha": area_ha,
                    "mean_ndvi_change": round(mean_diff, 4),
                    "mean_before_ndvi": round(mean_before, 4) if mean_before is not None else None,
                    "mean_after_ndvi": round(mean_after, 4) if mean_after is not None else None,
                },
            }
            features.append(feature)

    # Sort largest change polygons first
    features.sort(key=lambda f: f["properties"]["area_m2"], reverse=True)
    return features
