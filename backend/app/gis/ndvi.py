"""TerraLens Deterministic NDVI & Spectral Index Engine.

Provides core remote sensing raster calculations:
- Normalized Difference Vegetation Index (NDVI)
- Temporal NDVI Difference (delta NDVI)
- Vegetation Change Detection and Thresholding
- Georeferenced GeoTIFF creation preserving spatial metadata
"""

from pathlib import Path
from typing import Optional, Tuple, Union
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine


def calculate_ndvi(
    red: np.ndarray,
    nir: np.ndarray,
    nodata: float = -9999.0,
    eps: float = 1e-8,
) -> np.ndarray:
    """Calculate Normalized Difference Vegetation Index (NDVI) from Red and NIR arrays.

    NDVI = (NIR - Red) / (NIR + Red)

    Parameters
    ----------
    red : np.ndarray
        Red band reflectance array (e.g. Sentinel-2 Band 4).
    nir : np.ndarray
        Near-Infrared band reflectance array (e.g. Sentinel-2 Band 8).
    nodata : float
        NoData sentinel value for invalid or masked pixels (default: -9999.0).
    eps : float
        Small epsilon to prevent division by zero in near-zero sum cases.

    Returns
    -------
    np.ndarray
        Float32 array of NDVI values in range [-1.0, 1.0], with invalid pixels set to nodata.
    """
    if red.shape != nir.shape:
        raise ValueError(f"Array shape mismatch: red {red.shape} vs nir {nir.shape}")

    # Convert to float32
    red_f = red.astype(np.float32)
    nir_f = nir.astype(np.float32)

    # Build mask for valid input pixels
    # Invalid if either band is NaN, inf, equal to nodata, or negative reflectance
    valid_mask = (
        np.isfinite(red_f)
        & np.isfinite(nir_f)
        & (red_f != nodata)
        & (nir_f != nodata)
        & (red_f >= 0.0)
        & (nir_f >= 0.0)
    )

    numerator = nir_f - red_f
    denominator = nir_f + red_f

    # Output array initialized to nodata
    ndvi = np.full(red.shape, nodata, dtype=np.float32)

    # Calculate only on valid pixels with non-zero denominator
    calc_mask = valid_mask & (denominator > eps)
    zero_mask = valid_mask & (denominator <= eps)

    # Where both red and nir are ~0, NDVI is mathematically 0.0
    ndvi[zero_mask] = 0.0

    # Compute NDVI on valid non-zero denominator pixels
    calculated = numerator[calc_mask] / denominator[calc_mask]
    # Clip to valid theoretical physical bounds [-1.0, 1.0]
    ndvi[calc_mask] = np.clip(calculated, -1.0, 1.0)

    return ndvi


def calculate_ndvi_from_files(
    red_path: Union[str, Path],
    nir_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    nodata: float = -9999.0,
) -> Tuple[np.ndarray, dict]:
    """Load Red and NIR GeoTIFF bands, compute NDVI, and optionally write output GeoTIFF.

    Preserves exact raster CRS, affine transform, dimensions, and NoData.
    """
    red_p = Path(red_path)
    nir_p = Path(nir_path)

    if not red_p.exists():
        raise FileNotFoundError(f"Red band raster not found: {red_p}")
    if not nir_p.exists():
        raise FileNotFoundError(f"NIR band raster not found: {nir_p}")

    with rasterio.open(red_p) as red_src, rasterio.open(nir_p) as nir_src:
        if red_src.crs != nir_src.crs:
            raise ValueError(f"CRS mismatch: Red {red_src.crs} vs NIR {nir_src.crs}")
        if (red_src.width, red_src.height) != (nir_src.width, nir_src.height):
            raise ValueError(
                f"Dimension mismatch: Red ({red_src.width}x{red_src.height}) vs "
                f"NIR ({nir_src.width}x{nir_src.height})"
            )
        if red_src.transform != nir_src.transform:
            raise ValueError("Affine transform mismatch between Red and NIR bands")

        red_data = red_src.read(1)
        nir_data = nir_src.read(1)

        profile = red_src.profile.copy()
        profile.update(
            dtype=rasterio.float32,
            count=1,
            nodata=nodata,
            compress="deflate",
        )

    ndvi_array = calculate_ndvi(red_data, nir_data, nodata=nodata)

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_p, "w", **profile) as dst:
            dst.write(ndvi_array, 1)

    return ndvi_array, profile


def calculate_ndvi_difference(
    before_ndvi: np.ndarray,
    after_ndvi: np.ndarray,
    nodata: float = -9999.0,
) -> np.ndarray:
    """Calculate temporal NDVI difference: delta_NDVI = after_NDVI - before_NDVI.

    Negative values denote vegetation loss / canopy decrease.
    Positive values denote vegetation growth / regrowth.
    """
    if before_ndvi.shape != after_ndvi.shape:
        raise ValueError(
            f"Shape mismatch in NDVI difference: before {before_ndvi.shape} vs after {after_ndvi.shape}"
        )

    valid_mask = (
        np.isfinite(before_ndvi)
        & np.isfinite(after_ndvi)
        & (before_ndvi != nodata)
        & (after_ndvi != nodata)
    )

    diff = np.full(before_ndvi.shape, nodata, dtype=np.float32)
    diff[valid_mask] = after_ndvi[valid_mask] - before_ndvi[valid_mask]

    return diff


def calculate_ndvi_difference_from_files(
    before_ndvi_path: Union[str, Path],
    after_ndvi_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    nodata: float = -9999.0,
) -> Tuple[np.ndarray, dict]:
    """Calculate NDVI difference between two NDVI GeoTIFFs and optionally save result."""
    b_p = Path(before_ndvi_path)
    a_p = Path(after_ndvi_path)

    if not b_p.exists():
        raise FileNotFoundError(f"Before NDVI raster not found: {b_p}")
    if not a_p.exists():
        raise FileNotFoundError(f"After NDVI raster not found: {a_p}")

    with rasterio.open(b_p) as b_src, rasterio.open(a_p) as a_src:
        if b_src.crs != a_src.crs:
            raise ValueError(f"CRS mismatch: before {b_src.crs} vs after {a_src.crs}")
        if (b_src.width, b_src.height) != (a_src.width, a_src.height):
            raise ValueError("Dimension mismatch between before and after NDVI rasters")
        if b_src.transform != a_src.transform:
            raise ValueError("Affine transform mismatch between before and after NDVI rasters")

        b_data = b_src.read(1)
        a_data = a_src.read(1)

        profile = b_src.profile.copy()
        profile.update(
            dtype=rasterio.float32,
            count=1,
            nodata=nodata,
            compress="deflate",
        )

    diff_array = calculate_ndvi_difference(b_data, a_data, nodata=nodata)

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_p, "w", **profile) as dst:
            dst.write(diff_array, 1)

    return diff_array, profile


def detect_significant_change(
    ndvi_difference: np.ndarray,
    threshold: float = -0.20,
    increase_threshold: float = 0.20,
    nodata: float = -9999.0,
) -> np.ndarray:
    """Classify NDVI difference into significant vegetation change categories.

    Categories:
    - -1: Significant vegetation decrease (delta_NDVI <= threshold, e.g. <= -0.20)
    -  0: Unchanged / stable canopy (threshold < delta_NDVI < increase_threshold)
    - +1: Significant vegetation increase (delta_NDVI >= increase_threshold)
    - -9999: NoData

    Returns
    -------
    np.ndarray
        Int16 or Float32 classification array.
    """
    valid_mask = np.isfinite(ndvi_difference) & (ndvi_difference != nodata)

    # Initialize with NoData code
    classified = np.full(ndvi_difference.shape, -9999, dtype=np.int16)

    # Unchanged baseline
    classified[valid_mask] = 0

    # Vegetation decrease (potential loss)
    decrease_mask = valid_mask & (ndvi_difference <= threshold)
    classified[decrease_mask] = -1

    # Vegetation increase
    increase_mask = valid_mask & (ndvi_difference >= increase_threshold)
    classified[increase_mask] = 1

    return classified


def write_geotiff(
    output_path: Union[str, Path],
    data: np.ndarray,
    profile: dict,
    nodata: Optional[float] = None,
) -> Path:
    """Write 2D numpy array to georeferenced GeoTIFF."""
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    prof = profile.copy()
    if nodata is not None:
        prof["nodata"] = nodata
    prof["count"] = 1
    prof["compress"] = "deflate"

    with rasterio.open(out_p, "w", **prof) as dst:
        dst.write(data, 1)

    return out_p
