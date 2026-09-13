import { AOI, GeoJSONFeatureCollection, HealthStatus, SatelliteScene } from "../types";

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
