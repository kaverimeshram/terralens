import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Text, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from app.database.base import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aoi_id = Column(UUID(as_uuid=True), ForeignKey("aois.id", ondelete="CASCADE"), nullable=False, index=True)
    before_scene_id = Column(UUID(as_uuid=True), ForeignKey("satellite_scenes.id", ondelete="RESTRICT"), nullable=False)
    after_scene_id = Column(UUID(as_uuid=True), ForeignKey("satellite_scenes.id", ondelete="RESTRICT"), nullable=False)
    analysis_type = Column(String(100), nullable=False, default="NDVI_CHANGE")
    threshold = Column(Numeric(5, 3), nullable=False, default=-0.200)
    ndvi_change = Column(Numeric(5, 3), nullable=True)
    total_change_area_m2 = Column(Numeric(16, 2), default=0.0)
    status = Column(String(50), nullable=False, default="COMPLETED", index=True)
    validation_report = Column(JSONB, default=dict)
    agent_summary = Column(Text, nullable=True)
    activity_log = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    aoi = relationship("AOI", back_populates="analysis_runs")
    before_scene = relationship("SatelliteScene", foreign_keys=[before_scene_id])
    after_scene = relationship("SatelliteScene", foreign_keys=[after_scene_id])
    change_polygons = relationship("ChangePolygon", back_populates="analysis_run", cascade="all, delete-orphan")

    @property
    def total_change_area_ha(self) -> float:
        if self.total_change_area_m2 is not None:
            return float(self.total_change_area_m2) / 10000.0
        return 0.0


class ChangePolygon(Base):
    __tablename__ = "change_polygons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    geometry = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)
    area_m2 = Column(Numeric(16, 2), nullable=False)
    change_value = Column(Numeric(6, 4), nullable=False)
    mean_before_ndvi = Column(Numeric(5, 3), nullable=True)
    mean_after_ndvi = Column(Numeric(5, 3), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    analysis_run = relationship("AnalysisRun", back_populates="change_polygons")

    @property
    def area_ha(self) -> float:
        if self.area_m2 is not None:
            return float(self.area_m2) / 10000.0
        return 0.0

    @property
    def mean_ndvi_change(self) -> float:
        return float(self.change_value) if self.change_value is not None else 0.0

    @property
    def change_type(self) -> str:
        if self.change_value is not None and float(self.change_value) <= -0.20:
            return "detected vegetation decrease"
        elif self.change_value is not None and float(self.change_value) >= 0.20:
            return "detected vegetation increase"
        return "unchanged"
