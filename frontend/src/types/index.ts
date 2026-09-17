export interface BoundingBox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  center: [number, number];
}

export interface AOI {
  id: string;
  name: string;
  description: string;
  bounding_box: BoundingBox;
  area_hectares: number;
  created_at: string;
  geometry?: any;
}

export interface SatelliteScene {
  id: string;
  aoi_id: string;
  aoi_name?: string;
  scene_identifier: string;
  satellite: string;
  sensor: string;
  acquisition_date: string;
  cloud_cover: number;
  spatial_resolution: number;
  raster_path: string;
  red_band_path?: string;
  nir_band_path?: string;
  swir_band_path?: string;
  metadata: Record<string, any>;
}

export interface InfrastructureFeature {
  id: string;
  aoi_id?: string;
  name: string;
  type: string;
  distance_m?: number;
  distance_meters?: number;
  nearest_change_polygon_id?: string;
  change_polygon_area_m2?: number;
  metadata: Record<string, any>;
  geometry: {
    type: string;
    coordinates: any;
  };
}

export interface ChangePolygonProperties {
  id: string;
  analysis_run_id: string;
  change_type: string;
  area_m2: number;
  area_ha: number;
  mean_ndvi_change: number;
  mean_before_ndvi?: number | null;
  mean_after_ndvi?: number | null;
  created_at?: string;
}

export interface AnalysisRun {
  id: string;
  aoi_id: string;
  aoi_name: string;
  before_scene?: {
    id: string;
    scene_identifier: string;
    acquisition_date: string;
  };
  after_scene?: {
    id: string;
    scene_identifier: string;
    acquisition_date: string;
  };
  analysis_type: string;
  threshold: number;
  ndvi_change: number | null;
  total_change_area_m2: number;
  total_change_area_ha: number;
  change_polygon_count: number;
  status: string;
  validation_report?: Record<string, any>;
  created_at?: string;
}

export interface NearbyInfrastructureItem {
  id: string;
  aoi_id?: string;
  name: string;
  type: string;
  distance_m: number;
  nearest_change_polygon_id: string;
  change_polygon_area_m2: number;
  change_polygon_mean_ndvi_change: number;
  geometry?: any;
  metadata?: Record<string, any>;
}

export interface NearbyInfrastructureResponse {
  analysis_id: string;
  radius_m: number;
  infrastructure_count: number;
  infrastructure_by_type: Record<string, number>;
  closest_infrastructure: NearbyInfrastructureItem | null;
  associated_change_polygon_count: number;
  associated_change_area_m2: number;
  associated_change_area_ha: number;
  infrastructure: NearbyInfrastructureItem[];
  factual_summary: string[];
}

export interface SpatialSummaryResponse {
  analysis_id: string;
  radius_m: number;
  change_metrics: {
    change_polygon_count: number;
    total_change_area_m2: number;
    total_change_area_ha: number;
    min_polygon_area_m2: number;
    max_polygon_area_m2: number;
    mean_polygon_area_m2: number;
    mean_ndvi_change: number;
  };
  aoi_containment: {
    all_contained: boolean;
    total_polygons: number;
    contained_count: number;
    containment_ratio: number;
  };
  infrastructure_summary: {
    count_within_radius: number;
    by_type: Record<string, number>;
    closest_asset: NearbyInfrastructureItem | null;
    associated_change_area_ha: number;
    factual_statements: string[];
  };
  population_summary: {
    zones_within_radius: number;
    intersecting_zones_count: number;
    total_intersecting_population: number;
    factual_statements: string[];
  };
}

export interface PopulationZoneItem {
  id: string;
  aoi_id?: string;
  name: string;
  population: number;
  distance_m: number;
  intersects_change: boolean;
  zone_area_ha: number;
  intersection_area_ha: number;
  nearest_change_polygon_id: string;
  geometry?: any;
  metadata?: Record<string, any>;
}

export interface PopulationContextResponse {
  analysis_id: string;
  radius_m: number;
  population_zones_count: number;
  intersecting_zones_count: number;
  total_intersecting_population: number;
  zones: PopulationZoneItem[];
  factual_summary: string[];
}

export interface GeoJSONFeatureCollection<T = any> {
  type: "FeatureCollection";
  analysis_id?: string;
  radius_m?: number;
  count?: number;
  total_change_area_m2?: number;
  total_change_area_ha?: number;
  features: Array<{
    type: "Feature";
    id?: string;
    geometry: any;
    properties: T;
  }>;
}

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  environment: string;
  database: {
    connected: boolean;
    postgis_version: string;
    counts: {
      aois: number;
      satellite_scenes: number;
      infrastructure_features: number;
    };
  };
  gis_capabilities: Record<string, any>;
}
