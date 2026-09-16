"""TerraLens Deterministic GIS & Remote Sensing Engine."""

from app.gis.ndvi import (
    calculate_ndvi,
    calculate_ndvi_from_files,
    calculate_ndvi_difference,
    calculate_ndvi_difference_from_files,
    detect_significant_change,
    write_geotiff,
)
from app.gis.vectorization import (
    polygonize_change_raster,
    calculate_metric_area,
    extract_zonal_stats,
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

__all__ = [
    "calculate_ndvi",
    "calculate_ndvi_from_files",
    "calculate_ndvi_difference",
    "calculate_ndvi_difference_from_files",
    "detect_significant_change",
    "write_geotiff",
    "polygonize_change_raster",
    "calculate_metric_area",
    "extract_zonal_stats",
    "GISValidationError",
    "validate_raster_compatibility",
    "validate_ndvi_array",
    "validate_geometry_validity",
    "run_ndvi_change_analysis",
    "resolve_raster_path",
]
