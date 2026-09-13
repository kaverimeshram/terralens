"""TerraLens Database Seeder and Schema Initializer.

Initializes the PostgreSQL / PostGIS database and populates real seed datasets
(Mau Forest Complex, Harz National Park, Sentinel-2 scenes, infrastructure, and population zones).
"""

import json
import logging
import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from shapely.geometry import shape
from sqlalchemy import text
from geoalchemy2.shape import from_shape

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.database.session import sync_engine, SyncSessionLocal
from app.models.aoi import AOI
from app.models.scene import SatelliteScene
from app.models.infrastructure import Infrastructure, PopulationZone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_db")


def create_database_if_not_exists(db_name: str = "terralens"):
    """Connect to default postgres DB and ensure target database exists."""
    # Parse DB connection info from settings
    # Default fallback to localhost:5432 postgres
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            user=os.getenv("PGUSER", os.getenv("USER", "postgres")),
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';")
        exists = cur.fetchone()
        if not exists:
            logger.info(f"Database '{db_name}' does not exist. Creating database '{db_name}'...")
            cur.execute(f"CREATE DATABASE {db_name};")
            logger.info(f"Database '{db_name}' created successfully.")
        else:
            logger.info(f"Database '{db_name}' already exists.")
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Database check/creation notice: {e}. Assuming database is ready or managed externally.")


def apply_schema():
    """Apply schema.sql to the database."""
    schema_path = backend_dir / "migrations" / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")

    logger.info(f"Applying schema DDL from {schema_path}...")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with sync_engine.connect() as conn:
        conn.execute(text(schema_sql))
        conn.commit()
    logger.info("Schema DDL applied successfully with PostGIS extensions and spatial indexes.")


def seed_data():
    """Seed AOIs, satellite scenes, infrastructure, and population zones."""
    seed_dir = backend_dir / "data" / "seed"
    db = SyncSessionLocal()

    try:
        # 1. Seed AOIs
        aois_file = seed_dir / "aois.json"
        with open(aois_file, "r", encoding="utf-8") as f:
            aois_data = json.load(f)

        for item in aois_data:
            geom_shapely = shape(item["geometry"])
            aoi_record = AOI(
                id=item["id"],
                name=item["name"],
                description=item["description"],
                geometry=from_shape(geom_shapely, srid=4326),
                bounding_box=item.get("bounding_box"),
            )
            db.merge(aoi_record)
        db.commit()
        logger.info(f"Seeded {len(aois_data)} Areas of Interest (AOIs).")

        # 2. Seed Satellite Scenes
        scenes_file = seed_dir / "scenes.json"
        with open(scenes_file, "r", encoding="utf-8") as f:
            scenes_data = json.load(f)

        for item in scenes_data:
            scene_record = SatelliteScene(
                id=item["id"],
                aoi_id=item["aoi_id"],
                scene_identifier=item["scene_identifier"],
                satellite=item["satellite"],
                sensor=item["sensor"],
                acquisition_date=item["acquisition_date"],
                cloud_cover=item["cloud_cover"],
                spatial_resolution=item["spatial_resolution"],
                raster_path=item["raster_path"],
                red_band_path=item.get("red_band_path"),
                nir_band_path=item.get("nir_band_path"),
                swir_band_path=item.get("swir_band_path"),
                metadata_=item.get("metadata", {}),
            )
            db.merge(scene_record)
        db.commit()
        logger.info(f"Seeded {len(scenes_data)} Satellite Scenes.")

        # 3. Seed Infrastructure
        infra_file = seed_dir / "infrastructure.json"
        with open(infra_file, "r", encoding="utf-8") as f:
            infra_data = json.load(f)

        for item in infra_data:
            geom_shapely = shape(item["geometry"])
            infra_record = Infrastructure(
                id=item["id"],
                aoi_id=item.get("aoi_id"),
                name=item["name"],
                type=item["type"],
                geometry=from_shape(geom_shapely, srid=4326),
                metadata_=item.get("metadata", {}),
            )
            db.merge(infra_record)
        db.commit()
        logger.info(f"Seeded {len(infra_data)} Infrastructure features.")

        # 4. Seed Population Zones
        pop_file = seed_dir / "population_zones.json"
        with open(pop_file, "r", encoding="utf-8") as f:
            pop_data = json.load(f)

        for item in pop_data:
            geom_shapely = shape(item["geometry"])
            pop_record = PopulationZone(
                id=item["id"],
                aoi_id=item.get("aoi_id"),
                name=item["name"],
                population=item["population"],
                geometry=from_shape(geom_shapely, srid=4326),
                metadata_=item.get("metadata", {}),
            )
            db.merge(pop_record)
        db.commit()
        logger.info(f"Seeded {len(pop_data)} Population Zones.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error during seeding: {e}")
        raise
    finally:
        db.close()


def main():
    logger.info("Starting TerraLens Phase 1 database initialization...")
    create_database_if_not_exists()
    apply_schema()
    seed_data()
    logger.info("Database initialization and seeding completed successfully!")


if __name__ == "__main__":
    main()
