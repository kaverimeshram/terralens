-- TerraLens PostGIS Database Schema
-- Spatial Intelligence & Remote Sensing Analytics

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- Drop existing tables if re-initializing
DROP TABLE IF EXISTS population_zones CASCADE;
DROP TABLE IF EXISTS infrastructure CASCADE;
DROP TABLE IF EXISTS change_polygons CASCADE;
DROP TABLE IF EXISTS analysis_runs CASCADE;
DROP TABLE IF EXISTS satellite_scenes CASCADE;
DROP TABLE IF EXISTS aois CASCADE;

-- 1. Areas of Interest (AOIs)
CREATE TABLE aois (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    geometry GEOMETRY(Polygon, 4326) NOT NULL,
    bounding_box JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_aois_geom ON aois USING GIST (geometry);

-- 2. Satellite Scenes (Metadata & Imagery Index)
CREATE TABLE satellite_scenes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aoi_id UUID NOT NULL REFERENCES aois(id) ON DELETE CASCADE,
    scene_identifier VARCHAR(255) NOT NULL UNIQUE,
    satellite VARCHAR(100) NOT NULL,
    sensor VARCHAR(100) NOT NULL,
    acquisition_date DATE NOT NULL,
    cloud_cover NUMERIC(5,2) NOT NULL DEFAULT 0.0,
    spatial_resolution NUMERIC(6,2) NOT NULL DEFAULT 10.0,
    raster_path VARCHAR(500) NOT NULL,
    red_band_path VARCHAR(500),
    nir_band_path VARCHAR(500),
    swir_band_path VARCHAR(500),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_satellite_scenes_aoi ON satellite_scenes (aoi_id);
CREATE INDEX idx_satellite_scenes_date ON satellite_scenes (acquisition_date);

-- 3. Analysis Runs (Tracking Agent & GIS executions)
CREATE TABLE analysis_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aoi_id UUID NOT NULL REFERENCES aois(id) ON DELETE CASCADE,
    before_scene_id UUID NOT NULL REFERENCES satellite_scenes(id) ON DELETE RESTRICT,
    after_scene_id UUID NOT NULL REFERENCES satellite_scenes(id) ON DELETE RESTRICT,
    analysis_type VARCHAR(100) NOT NULL DEFAULT 'NDVI_CHANGE',
    threshold NUMERIC(5,3) NOT NULL DEFAULT -0.200,
    ndvi_change NUMERIC(5,3),
    total_change_area_m2 NUMERIC(16,2) DEFAULT 0.0,
    status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED', -- 'IN_PROGRESS', 'COMPLETED', 'VALIDATION_FAILED', 'FAILED'
    validation_report JSONB DEFAULT '{}'::jsonb,
    agent_summary TEXT,
    activity_log JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_analysis_runs_aoi ON analysis_runs (aoi_id);
CREATE INDEX idx_analysis_runs_status ON analysis_runs (status);

-- 4. Change Polygons (Vectorized raster change detections)
CREATE TABLE change_polygons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_m2 NUMERIC(16,2) NOT NULL,
    change_value NUMERIC(6,4) NOT NULL,
    mean_before_ndvi NUMERIC(5,3),
    mean_after_ndvi NUMERIC(5,3),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_change_polygons_geom ON change_polygons USING GIST (geometry);
CREATE INDEX idx_change_polygons_run ON change_polygons (analysis_run_id);

-- 5. Infrastructure Features (Real landmarks, roads, ranger stations, water bodies, power lines)
CREATE TABLE infrastructure (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aoi_id UUID REFERENCES aois(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(100) NOT NULL, -- 'Ranger Station', 'Access Road', 'Watchtower', 'Dam/Reservoir', 'Power Line', 'Bridge'
    geometry GEOMETRY(Geometry, 4326) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_infrastructure_geom ON infrastructure USING GIST (geometry);
CREATE INDEX idx_infrastructure_type ON infrastructure (type);

-- 6. Population Zones (Settlement zones, villages, urban clusters)
CREATE TABLE population_zones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aoi_id UUID REFERENCES aois(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    population INTEGER NOT NULL DEFAULT 0,
    geometry GEOMETRY(Polygon, 4326) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_population_zones_geom ON population_zones USING GIST (geometry);
