import uuid
from datetime import datetime
from sqlalchemy import Column, String, Date, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database.base import Base


class SatelliteScene(Base):
    __tablename__ = "satellite_scenes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aoi_id = Column(UUID(as_uuid=True), ForeignKey("aois.id", ondelete="CASCADE"), nullable=False, index=True)
    scene_identifier = Column(String(255), nullable=False, unique=True, index=True)
    satellite = Column(String(100), nullable=False)
    sensor = Column(String(100), nullable=False)
    acquisition_date = Column(Date, nullable=False, index=True)
    cloud_cover = Column(Numeric(5, 2), nullable=False, default=0.0)
    spatial_resolution = Column(Numeric(6, 2), nullable=False, default=10.0)
    raster_path = Column(String(500), nullable=False)
    red_band_path = Column(String(500), nullable=True)
    nir_band_path = Column(String(500), nullable=True)
    swir_band_path = Column(String(500), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    aoi = relationship("AOI", back_populates="scenes")
