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
  name: string;
  type: string;
  distance_meters?: number;
  metadata: Record<string, any>;
  geometry: {
    type: string;
    coordinates: any;
  };
}

export interface GeoJSONFeatureCollection<T = any> {
  type: "FeatureCollection";
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
