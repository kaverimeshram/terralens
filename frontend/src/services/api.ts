import {
  AOI,
  GeoJSONFeatureCollection,
  HealthStatus,
  SatelliteScene,
  AnalysisRun,
  ChangePolygonProperties,
  NearbyInfrastructureResponse,
  SpatialSummaryResponse,
  PopulationContextResponse,
} from "../types";

const API_BASE = "/api";

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Healthcheck failed: ${res.statusText}`);
  return res.json();
}

export async function fetchAOIs(): Promise<GeoJSONFeatureCollection<AOI>> {
  const res = await fetch(`${API_BASE}/aois?format=geojson`);
  if (!res.ok) throw new Error(`Failed to fetch AOIs: ${res.statusText}`);
  return res.json();
}

export async function fetchAOIScenes(aoiId: string): Promise<SatelliteScene[]> {
  const res = await fetch(`${API_BASE}/aois/${aoiId}/scenes`);
  if (!res.ok) throw new Error(`Failed to fetch scenes: ${res.statusText}`);
  const data = await res.json();
  return data.scenes || [];
}

export async function fetchAOIInfrastructure(aoiId: string): Promise<GeoJSONFeatureCollection> {
  const res = await fetch(`${API_BASE}/aois/${aoiId}/infrastructure`);
  if (!res.ok) throw new Error(`Failed to fetch infrastructure: ${res.statusText}`);
  return res.json();
}

export async function fetchNearbyInfrastructure(lon: number, lat: number, radiusMeters: number = 5000): Promise<GeoJSONFeatureCollection> {
  const res = await fetch(`${API_BASE}/infrastructure/nearby?lon=${lon}&lat=${lat}&radius_meters=${radiusMeters}`);
  if (!res.ok) throw new Error(`Failed to search nearby infrastructure: ${res.statusText}`);
  return res.json();
}

export async function runNDVIAnalysis(payload: {
  aoi_id: string;
  before_scene_id: string;
  after_scene_id: string;
  threshold?: number;
  minimum_area_m2?: number;
}): Promise<any> {
  const res = await fetch(`${API_BASE}/analysis/ndvi-change`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Analysis failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchAnalysisChanges(analysisId: string): Promise<GeoJSONFeatureCollection<ChangePolygonProperties>> {
  const res = await fetch(`${API_BASE}/analysis/${analysisId}/changes`);
  if (!res.ok) throw new Error(`Failed to fetch change polygons: ${res.statusText}`);
  return res.json();
}

export async function fetchAnalysisRuns(): Promise<AnalysisRun[]> {
  const res = await fetch(`${API_BASE}/analysis`);
  if (!res.ok) throw new Error(`Failed to fetch analysis runs: ${res.statusText}`);
  const data = await res.json();
  return data.analysis_runs || [];
}

export async function fetchAnalysisRun(analysisId: string): Promise<AnalysisRun> {
  const res = await fetch(`${API_BASE}/analysis/${analysisId}`);
  if (!res.ok) throw new Error(`Failed to fetch analysis run: ${res.statusText}`);
  return res.json();
}

export async function fetchAnalysisNearbyInfrastructure(
  analysisId: string,
  radiusM: number = 1000,
  format: "json" | "geojson" = "json"
): Promise<NearbyInfrastructureResponse | GeoJSONFeatureCollection> {
  const res = await fetch(`${API_BASE}/analysis/${analysisId}/nearby-infrastructure?radius_m=${radiusM}&format=${format}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Failed to fetch nearby infrastructure: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchAnalysisSpatialSummary(
  analysisId: string,
  radiusM: number = 1000
): Promise<SpatialSummaryResponse> {
  const res = await fetch(`${API_BASE}/analysis/${analysisId}/spatial-summary?radius_m=${radiusM}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Failed to fetch spatial summary: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchAnalysisPopulationContext(
  analysisId: string,
  radiusM: number = 1000,
  format: "json" | "geojson" = "json"
): Promise<PopulationContextResponse | GeoJSONFeatureCollection> {
  const res = await fetch(`${API_BASE}/analysis/${analysisId}/population-context?radius_m=${radiusM}&format=${format}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Failed to fetch population context: ${res.statusText}`);
  }
  return res.json();
}
