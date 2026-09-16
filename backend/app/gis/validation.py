"""TerraLens GIS & Remote Sensing Validation Layer.

Enforces deterministic quality gates:
- Raster grid alignment (CRS, dimensions, affine transform)
- Scene & AOI relational integrity
- Physical NDVI value ranges
- Geometry validity and noise thresholds
"""

from pathlib import Path
from typing import Optional, Tuple, Union
import numpy as np
import rasterio
from rasterio.crs import CRS
from shapely.geometry.base import BaseGeometry


class GISValidationError(ValueError):
    """Custom exception raised when GIS remote sensing validation gates fail."""
    pass


def validate_raster_compatibility(
    raster_path_a: Union[str, Path],
    raster_path_b: Union[str, Path],
    tolerance: float = 1e-6,
) -> Tuple[dict, dict]:
    """Verify that two raster datasets share identical CRS, grid dimensions, and affine transform.

    Parameters
    ----------
    raster_path_a : str or Path
        First raster file path.
    raster_path_b : str or Path
        Second raster file path.
    tolerance : float
        Numerical tolerance for affine transform floating-point comparison.

    Returns
    -------
    Tuple[dict, dict]
        (profile_a, profile_b)

    Raises
    ------
    GISValidationError
        If files are missing or grids do not align.
    """
    p_a = Path(raster_path_a)
    p_b = Path(raster_path_b)

    if not p_a.exists():
        raise GISValidationError(f"Raster file not found: {p_a}")
    if not p_b.exists():
        raise GISValidationError(f"Raster file not found: {p_b}")

    with rasterio.open(p_a) as src_a, rasterio.open(p_b) as src_b:
        # 1. CRS comparison
        if src_a.crs != src_b.crs:
            raise GISValidationError(
                f"CRS mismatch between rasters: '{src_a.crs}' vs '{src_b.crs}'"
            )

        # 2. Dimensions comparison
        if (src_a.width, src_a.height) != (src_b.width, src_b.height):
            raise GISValidationError(
                f"Dimension mismatch between rasters: "
                f"({src_a.width}x{src_a.height}) vs ({src_b.width}x{src_b.height})"
            )

        # 3. Affine transform comparison
        t_a = src_a.transform
        t_b = src_b.transform
        for i in range(6):
            if abs(t_a[i] - t_b[i]) > tolerance:
                raise GISValidationError(
                    f"Affine transform mismatch between rasters: {t_a} vs {t_b}"
                )

        # 4. Bounds comparison
        b_a = src_a.bounds
        b_b = src_b.bounds
        if (
            abs(b_a.left - b_b.left) > tolerance
            or abs(b_a.bottom - b_b.bottom) > tolerance
            or abs(b_a.right - b_b.right) > tolerance
            or abs(b_a.top - b_b.top) > tolerance
        ):
            raise GISValidationError(
                f"Bounding box mismatch between rasters: {b_a} vs {b_b}"
            )

        return src_a.profile, src_b.profile


def validate_ndvi_array(
    ndvi_array: np.ndarray,
    nodata: float = -9999.0,
) -> bool:
    """Validate that computed NDVI array contains valid numerical values within [-1.0, 1.0]."""
    valid_mask = np.isfinite(ndvi_array) & (ndvi_array != nodata)
    if not np.any(valid_mask):
        raise GISValidationError("NDVI calculation produced no valid pixels (all NoData/NaN)")

    valid_vals = ndvi_array[valid_mask]
    min_val = np.min(valid_vals)
    max_val = np.max(valid_vals)

    # Physical bounds check with small numerical tolerance
    if min_val < -1.001 or max_val > 1.001:
        raise GISValidationError(
            f"NDVI values out of theoretical physical bounds [-1.0, 1.0]: min={min_val:.4f}, max={max_val:.4f}"
        )

    return True


def validate_geometry_validity(
    geom: BaseGeometry,
    min_area_m2: float = 0.0,
    area_m2: Optional[float] = None,
) -> bool:
    """Validate that vector geometry is non-empty, valid, and meets minimum area."""
    if geom is None or geom.is_empty:
        raise GISValidationError("Geometry is null or empty")

    if not geom.is_valid:
        raise GISValidationError("Geometry is topologically invalid")

    if area_m2 is not None and area_m2 < min_area_m2:
        raise GISValidationError(
            f"Geometry area ({area_m2:.1f} m²) below minimum threshold ({min_area_m2:.1f} m²)"
        )

    return True
