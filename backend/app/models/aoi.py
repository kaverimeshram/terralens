import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from app.database.base import Base


class AOI(Base):
    __tablename__ = "aois"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    bounding_box = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    scenes = relationship("SatelliteScene", back_populates="aoi", cascade="all, delete-orphan")
    analysis_runs = relationship("AnalysisRun", back_populates="aoi", cascade="all, delete-orphan")
    infrastructure_items = relationship("Infrastructure", back_populates="aoi")
    population_zones = relationship("PopulationZone", back_populates="aoi")
