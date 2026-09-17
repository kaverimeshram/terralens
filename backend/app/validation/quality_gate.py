"""TerraLens Quality Gate Engine.

Enforces deterministic remote sensing and spatial quality gates:
1. AOI Existence & Boundary Validity Gate
2. Satellite Scene Metadata & Cloud Cover Gate (≤ 20% cloud cover limit)
3. Radiometric Delta & Significant Change Gate (verifies meaningful NDVI change)
4. Noise Filter & Geometry Integrity Gate (minimum 500 m² surface area & valid topology)
5. PostGIS AOI Topological Containment Gate (verifies 100% containment in target AOI)
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import QualityGateReport, GateCheckDetail
from app.gis.spatial_service import validate_aoi_containment

logger = logging.getLogger("terralens.validation.quality_gate")


class QualityGate:
    """Evaluates multi-stage deterministic quality gates for remote sensing analyses."""

    @staticmethod
    async def evaluate(
        db: AsyncSession,
        aoi_id: uuid.UUID,
        before_scene_id: Optional[uuid.UUID] = None,
        after_scene_id: Optional[uuid.UUID] = None,
        analysis_id: Optional[uuid.UUID] = None,
        max_cloud_cover: float = 20.0,
        threshold: float = -0.20,
        min_area_m2: float = 500.0,
    ) -> QualityGateReport:
        """Run all applicable deterministic quality gate checks."""
        checks: List[GateCheckDetail] = []
        failed_reasons: List[str] = []

        # --- 1. AOI Existence & Boundary Gate ---
        aoi_query = text("SELECT id, name, ST_IsValid(geometry) as is_valid FROM aois WHERE id = :id;")
        aoi_res = await db.execute(aoi_query, {"id": aoi_id})
        aoi_row = aoi_res.fetchone()

        if not aoi_row:
            checks.append(
                GateCheckDetail(
                    gate_name="AOI_EXISTENCE_GATE",
                    status="FAILED",
                    description=f"Area of Interest with ID '{aoi_id}' does not exist in database.",
                    value=str(aoi_id),
                )
            )
            failed_reasons.append(f"AOI '{aoi_id}' not found")
        else:
            is_geom_valid = bool(aoi_row.is_valid)
            checks.append(
                GateCheckDetail(
                    gate_name="AOI_EXISTENCE_GATE",
                    status="PASSED" if is_geom_valid else "FAILED",
                    description=f"AOI '{aoi_row.name}' exists and has valid PostGIS polygon boundary.",
                    value={"name": aoi_row.name, "geometry_valid": is_geom_valid},
                )
            )
            if not is_geom_valid:
                failed_reasons.append(f"AOI '{aoi_row.name}' has invalid polygon geometry")

        # --- 2. Satellite Scene Metadata & Cloud Cover Gate ---
        if before_scene_id and after_scene_id:
            scenes_query = text(
                """
                SELECT id, aoi_id, scene_identifier, cloud_cover, red_band_path, nir_band_path 
                FROM satellite_scenes 
                WHERE id IN (:before_id, :after_id);
                """
            )
            scenes_res = await db.execute(scenes_query, {"before_id": before_scene_id, "after_id": after_scene_id})
            scenes_map = {str(r.id): r for r in scenes_res.fetchall()}

            before_scene = scenes_map.get(str(before_scene_id))
            after_scene = scenes_map.get(str(after_scene_id))

            if not before_scene or not after_scene:
                missing = []
                if not before_scene:
                    missing.append(f"before scene ({before_scene_id})")
                if not after_scene:
                    missing.append(f"after scene ({after_scene_id})")
                checks.append(
                    GateCheckDetail(
                        gate_name="SCENE_METADATA_GATE",
                        status="FAILED",
                        description=f"Required satellite scenes missing from catalog: {', '.join(missing)}.",
                    )
                )
                failed_reasons.append(f"Missing scenes: {', '.join(missing)}")
            else:
                # Check AOI association
                if before_scene.aoi_id != aoi_id or after_scene.aoi_id != aoi_id:
                    checks.append(
                        GateCheckDetail(
                            gate_name="SCENE_AOI_ALIGNMENT_GATE",
                            status="FAILED",
                            description="Selected satellite scenes do not match the target AOI.",
                        )
                    )
                    failed_reasons.append("Scenes belong to a different AOI")
                else:
                    checks.append(
                        GateCheckDetail(
                            gate_name="SCENE_AOI_ALIGNMENT_GATE",
                            status="PASSED",
                            description="Both satellite scenes belong to the specified AOI.",
                        )
                    )

                # Check Cloud Cover Constraint
                before_cloud = float(before_scene.cloud_cover)
                after_cloud = float(after_scene.cloud_cover)
                max_observed_cloud = max(before_cloud, after_cloud)

                if max_observed_cloud > max_cloud_cover:
                    violating_scene = before_scene if before_cloud > max_cloud_cover else after_scene
                    violating_val = max(before_cloud, after_cloud)
                    checks.append(
                        GateCheckDetail(
                            gate_name="CLOUD_COVER_GATE",
                            status="FAILED",
                            description=f"Scene '{violating_scene.scene_identifier}' exceeds cloud cover threshold ({violating_val}% > {max_cloud_cover}%). High cloud contamination prevents reliable NDVI change analysis.",
                            value=violating_val,
                            threshold=max_cloud_cover,
                        )
                    )
                    failed_reasons.append(
                        f"Cloud cover exceeded limit ({violating_val}% > {max_cloud_cover}%) in {violating_scene.scene_identifier}"
                    )
                else:
                    checks.append(
                        GateCheckDetail(
                            gate_name="CLOUD_COVER_GATE",
                            status="PASSED",
                            description=f"Cloud cover is within acceptable remote sensing threshold (Before: {before_cloud}%, After: {after_cloud}%, Limit: {max_cloud_cover}%).",
                            value={"before_cloud": before_cloud, "after_cloud": after_cloud},
                            threshold=max_cloud_cover,
                        )
                    )

        # --- 3. Radiometric Delta & Significant Change Gate ---
        if analysis_id:
            run_query = text("SELECT id, ndvi_change, total_change_area_m2, status FROM analysis_runs WHERE id = :id;")
            run_res = await db.execute(run_query, {"id": analysis_id})
            run_row = run_res.fetchone()

            if run_row:
                total_m2 = float(run_row.total_change_area_m2 or 0.0)
                mean_delta = float(run_row.ndvi_change or 0.0)

                # Count change polygons
                poly_count_query = text("SELECT COUNT(*) FROM change_polygons WHERE analysis_run_id = :id;")
                poly_count = (await db.execute(poly_count_query, {"id": analysis_id})).scalar_one()

                if poly_count == 0 or total_m2 == 0.0:
                    checks.append(
                        GateCheckDetail(
                            gate_name="RADIOMETRIC_DELTA_GATE",
                            status="PASSED",  # Valid execution, stable canopy
                            description=f"No significant vegetation decrease detected (changed pixels: 0, area: 0.0 ha, threshold: {threshold}). Forest canopy remained stable.",
                            value={"polygon_count": 0, "total_area_ha": 0.0, "mean_polygon_ndvi_change": 0.0, "global_mean_ndvi_difference": round(mean_delta, 4)},
                            threshold=threshold,
                        )
                    )
                else:
                    # Query change_polygons for exact polygon-level NDVI change statistics
                    poly_stats_query = text(
                        """
                        SELECT 
                            COALESCE(AVG(change_value), 0.0) as avg_poly_delta,
                            COALESCE(MAX(change_value), 0.0) as max_poly_delta
                        FROM change_polygons 
                        WHERE analysis_run_id = :id;
                        """
                    )
                    poly_stats_res = await db.execute(poly_stats_query, {"id": analysis_id})
                    poly_stats = poly_stats_res.fetchone()
                    avg_poly_delta = float(poly_stats.avg_poly_delta)
                    max_poly_delta = float(poly_stats.max_poly_delta)

                    # Verify that detected polygons actually satisfy the significant decrease threshold
                    if max_poly_delta > threshold:
                        checks.append(
                            GateCheckDetail(
                                gate_name="RADIOMETRIC_DELTA_GATE",
                                status="FAILED",
                                description=f"Detected polygons contain sub-threshold NDVI change values ({max_poly_delta:.4f} > {threshold:.2f}).",
                                value={"polygon_count": poly_count, "max_polygon_ndvi_change": round(max_poly_delta, 4)},
                                threshold=threshold,
                            )
                        )
                        failed_reasons.append(f"Polygon NDVI change does not satisfy threshold ({max_poly_delta:.4f} > {threshold:.2f})")
                    else:
                        checks.append(
                            GateCheckDetail(
                                gate_name="RADIOMETRIC_DELTA_GATE",
                                status="PASSED",
                                description=(
                                    f"Verified {poly_count} significant change polygon(s) totaling {total_m2/10000.0:.2f} ha "
                                    f"(mean polygon ΔNDVI: {avg_poly_delta:.4f} <= {threshold:.2f}, global scene ΔNDVI: {mean_delta:.4f})."
                                ),
                                value={
                                    "polygon_count": poly_count,
                                    "total_area_ha": round(total_m2 / 10000.0, 4),
                                    "mean_polygon_ndvi_change": round(avg_poly_delta, 4),
                                    "global_mean_ndvi_difference": round(mean_delta, 4),
                                },
                                threshold=threshold,
                            )
                        )

                # --- 4. Noise Filter & Geometry Gate ---
                if poly_count > 0:
                    min_area_query = text("SELECT MIN(area_m2) FROM change_polygons WHERE analysis_run_id = :id;")
                    observed_min_area = float((await db.execute(min_area_query, {"id": analysis_id})).scalar_one() or 0.0)

                    if observed_min_area < min_area_m2:
                        checks.append(
                            GateCheckDetail(
                                gate_name="NOISE_SUPPRESSION_GATE",
                                status="FAILED",
                                description=f"Polygons smaller than minimum area threshold ({observed_min_area:.1f} m² < {min_area_m2} m²) found.",
                                value=observed_min_area,
                                threshold=min_area_m2,
                            )
                        )
                        failed_reasons.append(f"Sub-threshold noise polygon detected ({observed_min_area:.1f} m²)")
                    else:
                        checks.append(
                            GateCheckDetail(
                                gate_name="NOISE_SUPPRESSION_GATE",
                                status="PASSED",
                                description=f"All detected polygons satisfy the {min_area_m2:.0f} m² noise suppression threshold (smallest polygon: {observed_min_area:.1f} m²).",
                                value=observed_min_area,
                                threshold=min_area_m2,
                            )
                        )

                # --- 5. PostGIS AOI Topological Containment Gate ---
                containment = await validate_aoi_containment(db=db, analysis_id=analysis_id)
                if not containment["all_polygons_contained"]:
                    checks.append(
                        GateCheckDetail(
                            gate_name="AOI_CONTAINMENT_GATE",
                            status="FAILED",
                            description=f"{containment['outside_polygons_count']} polygon(s) lie outside the official AOI boundary.",
                            value=containment["containment_ratio"],
                            threshold=1.0,
                        )
                    )
                    failed_reasons.append("Change polygons spill outside AOI boundary")
                else:
                    checks.append(
                        GateCheckDetail(
                            gate_name="AOI_CONTAINMENT_GATE",
                            status="PASSED",
                            description=f"100% of detected change polygons are strictly contained within AOI boundary (containment ratio: {containment['containment_ratio']:.4f}).",
                            value=containment["containment_ratio"],
                            threshold=1.0,
                        )
                    )

        passed_count = sum(1 for c in checks if c.status == "PASSED")
        failed_count = sum(1 for c in checks if c.status == "FAILED")
        overall_status = "PASSED" if failed_count == 0 else "VALIDATION_FAILED"

        return QualityGateReport(
            status=overall_status,
            total_checks=len(checks),
            passed_checks=passed_count,
            failed_checks=failed_count,
            gate_checks=checks,
            failure_reason="; ".join(failed_reasons) if failed_reasons else None,
        )
