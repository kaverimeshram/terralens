import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from app.database.base import Base


class Infrastructure(Base):
    __tablename__ = "infrastructure"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aoi_id = Column(UUID(as_uuid=True), ForeignKey("aois.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(100), nullable=False, index=True)
    geometry = Column(Geometry(geometry_type="GEOMETRY", srid=4326), nullable=False)
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    aoi = relationship("AOI", back_populates="infrastructure_items")


class PopulationZone(Base):
    __tablename__ = "population_zones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aoi_id = Column(UUID(as_uuid=True), ForeignKey("aois.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    population = Column(Integer, nullable=False, default=0)
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    aoi = relationship("AOI", back_populates="population_zones")
