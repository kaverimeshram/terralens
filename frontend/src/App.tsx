import { useEffect, useState } from "react";
import {
  Activity,
  Layers,
  MapPin,
  Satellite,
  ShieldCheck,
  CheckCircle2,
  Database,
  Radio,
  ExternalLink,
} from "lucide-react";
import { fetchHealth, fetchAOIs, fetchAOIScenes, fetchAOIInfrastructure, fetchNearbyInfrastructure } from "./services/api";
import { AOI, GeoJSONFeatureCollection, HealthStatus, SatelliteScene } from "./types";

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [, setLoading] = useState<boolean>(true);
  const [aois, setAois] = useState<AOI[]>([]);
  const [selectedAoi, setSelectedAoi] = useState<AOI | null>(null);
  const [scenes, setScenes] = useState<SatelliteScene[]>([]);
  const [infra, setInfra] = useState<GeoJSONFeatureCollection | null>(null);
  const [nearbyResults, setNearbyResults] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<"scenes" | "infrastructure" | "spatial">("scenes");

  useEffect(() => {
    loadInitialData();
  }, []);

  async function loadInitialData() {
    setLoading(true);
    try {
      const healthData = await fetchHealth();
      setHealth(healthData);

      const aoisGeo = await fetchAOIs();
      const aoiList = aoisGeo.features.map((f) => ({
        ...f.properties,
        geometry: f.geometry,
      }));
      setAois(aoiList);

      if (aoiList.length > 0) {
        selectAoi(aoiList[0]);
      }
    } catch (err) {
      console.error("Initialization error:", err);
    } finally {
      setLoading(false);
    }
  }

  async function selectAoi(aoi: AOI) {
    setSelectedAoi(aoi);
    try {
      const [scenesData, infraData] = await Promise.all([
        fetchAOIScenes(aoi.id),
        fetchAOIInfrastructure(aoi.id),
      ]);
      setScenes(scenesData);
      setInfra(infraData);

      // Perform sample nearby proximity search around AOI center
      if (aoi.bounding_box?.center) {
        const [lon, lat] = aoi.bounding_box.center;
        const nearby = await fetchNearbyInfrastructure(lon, lat, 10000);
        setNearbyResults(nearby.features);
      }
    } catch (err) {
      console.error("Failed to load AOI details:", err);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", backgroundColor: "var(--bg-primary)" }}>
      {/* Top Header */}
      <header
        style={{
          height: "56px",
          borderBottom: "1px solid var(--border-color)",
          backgroundColor: "var(--bg-secondary)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 20px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "6px",
              backgroundColor: "rgba(6, 182, 212, 0.15)",
              border: "1px solid rgba(6, 182, 212, 0.4)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--accent-cyan)",
            }}
          >
            <Satellite size={18} />
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontWeight: 700, letterSpacing: "0.5px", fontSize: "16px" }}>TerraLens</span>
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 600,
                  padding: "2px 6px",
                  borderRadius: "4px",
                  backgroundColor: "rgba(16, 185, 129, 0.15)",
                  color: "var(--accent-emerald)",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                }}
              >
                PHASE 1 ACTIVE
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              AI-Powered Satellite & Spatial Intelligence Engine
            </div>
          </div>
        </div>

        {/* Database & System Status Badge */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              fontSize: "12px",
              padding: "4px 10px",
              borderRadius: "6px",
              backgroundColor: health?.database?.connected ? "rgba(16, 185, 129, 0.1)" : "rgba(244, 63, 94, 0.1)",
              border: `1px solid ${health?.database?.connected ? "rgba(16, 185, 129, 0.3)" : "rgba(244, 63, 94, 0.3)"}`,
              color: health?.database?.connected ? "var(--accent-emerald)" : "var(--accent-rose)",
            }}
          >
            <Database size={14} />
            <span>{health?.database?.connected ? "PostGIS Connected" : "PostGIS Offline"}</span>
          </div>

          <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
            <span style={{ color: "var(--text-muted)" }}>Study Areas: </span>
            <strong style={{ color: "var(--text-primary)" }}>{aois.length}</strong>
          </div>

          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "4px",
              fontSize: "12px",
              color: "var(--accent-cyan)",
              textDecoration: "none",
              padding: "4px 8px",
              borderRadius: "4px",
              border: "1px solid rgba(6, 182, 212, 0.2)",
            }}
          >
            <span>API Docs</span>
            <ExternalLink size={12} />
          </a>
        </div>
      </header>

      {/* Main Grid Workspace */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "360px 1fr", overflow: "hidden" }}>
        {/* Left Sidebar / AOI & Control Panel */}
        <aside
          style={{
            backgroundColor: "var(--bg-secondary)",
            borderRight: "1px solid var(--border-color)",
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
          }}
        >
          {/* AOI Selector */}
          <div style={{ padding: "16px", borderBottom: "1px solid var(--border-color)" }}>
            <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "1px", color: "var(--text-muted)", marginBottom: "8px", fontWeight: 600 }}>
              Study Area (AOI)
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {aois.map((aoi) => {
                const isSelected = selectedAoi?.id === aoi.id;
                return (
                  <button
                    key={aoi.id}
                    onClick={() => selectAoi(aoi)}
                    style={{
                      textAlign: "left",
                      padding: "10px 12px",
                      borderRadius: "6px",
                      backgroundColor: isSelected ? "var(--bg-surface)" : "transparent",
                      border: `1px solid ${isSelected ? "var(--border-focus)" : "var(--border-subtle)"}`,
                      color: isSelected ? "var(--text-primary)" : "var(--text-secondary)",
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: "13px", marginBottom: "4px", color: isSelected ? "var(--accent-cyan)" : "var(--text-primary)" }}>
                      {aoi.name}
                    </div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", lineHeight: 1.4 }}>
                      {aoi.description.slice(0, 90)}...
                    </div>
                    <div style={{ marginTop: "6px", display: "flex", gap: "10px", fontSize: "10px", color: "var(--text-secondary)" }}>
                      <span>Area: {aoi.area_hectares.toLocaleString()} ha</span>
                      <span>EPSG:4326</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Sub-tabs for AOI assets */}
          <div style={{ display: "flex", borderBottom: "1px solid var(--border-color)", backgroundColor: "var(--bg-primary)" }}>
            <button
              onClick={() => setActiveTab("scenes")}
              style={{
                flex: 1,
                padding: "10px 0",
                fontSize: "12px",
                fontWeight: 500,
                background: "none",
                border: "none",
                borderBottom: activeTab === "scenes" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "scenes" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              Scenes ({scenes.length})
            </button>
            <button
              onClick={() => setActiveTab("infrastructure")}
              style={{
                flex: 1,
                padding: "10px 0",
                fontSize: "12px",
                fontWeight: 500,
                background: "none",
                border: "none",
                borderBottom: activeTab === "infrastructure" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "infrastructure" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              Infrastructure ({infra?.features?.length || 0})
            </button>
            <button
              onClick={() => setActiveTab("spatial")}
              style={{
                flex: 1,
                padding: "10px 0",
                fontSize: "12px",
                fontWeight: 500,
                background: "none",
                border: "none",
                borderBottom: activeTab === "spatial" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "spatial" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              Spatial Query
            </button>
          </div>

          {/* Tab Content */}
          <div style={{ flex: 1, padding: "16px", overflowY: "auto" }}>
            {activeTab === "scenes" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {scenes.map((scene) => (
                  <div
                    key={scene.id}
                    style={{
                      padding: "12px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      fontSize: "12px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{scene.satellite}</span>
                      <span
                        style={{
                          fontSize: "10px",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          backgroundColor: scene.cloud_cover > 20 ? "rgba(245, 158, 11, 0.15)" : "rgba(16, 185, 129, 0.15)",
                          color: scene.cloud_cover > 20 ? "var(--accent-amber)" : "var(--accent-emerald)",
                        }}
                      >
                        {scene.cloud_cover}% Cloud
                      </span>
                    </div>
                    <div style={{ color: "var(--text-muted)", fontSize: "11px", fontFamily: "var(--font-mono)", marginBottom: "6px" }}>
                      {scene.scene_identifier}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px", fontSize: "11px", color: "var(--text-secondary)" }}>
                      <div>Acquired: <strong>{scene.acquisition_date}</strong></div>
                      <div>Resolution: <strong>{scene.spatial_resolution}m</strong></div>
                      <div>Sensor: <strong>{scene.sensor.split(" ")[0]}</strong></div>
                      <div>Bands: <strong>B04, B08, B11</strong></div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === "infrastructure" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {infra?.features?.map((f, i) => (
                  <div
                    key={f.id || i}
                    style={{
                      padding: "10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      fontSize: "12px",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "var(--text-primary)", marginBottom: "2px" }}>
                      {f.properties.name}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted)" }}>
                      <span style={{ color: "var(--accent-cyan)" }}>{f.properties.type}</span>
                      <span>{f.geometry.type}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === "spatial" && (
              <div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "12px" }}>
                  Real PostGIS <code style={{ color: "var(--accent-cyan)" }}>ST_DWithin</code> & <code style={{ color: "var(--accent-cyan)" }}>ST_Distance</code> spatial proximity calculation from study area center:
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {nearbyResults.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "10px",
                        borderRadius: "6px",
                        backgroundColor: "var(--bg-surface)",
                        border: "1px solid var(--border-color)",
                        fontSize: "12px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: 600 }}>{item.properties.name}</span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--accent-emerald)" }}>
                          {(item.properties.distance_meters / 1000).toFixed(2)} km
                        </span>
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
                        Type: {item.properties.type}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </aside>

        {/* Right Main Panel / Spatial Intelligence Overview */}
        <main style={{ padding: "24px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* AOI Overview Card */}
          {selectedAoi && (
            <div
              style={{
                backgroundColor: "var(--bg-secondary)",
                borderRadius: "8px",
                border: "1px solid var(--border-color)",
                padding: "20px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
                <div>
                  <h2 style={{ fontSize: "18px", fontWeight: 700, color: "var(--text-primary)" }}>{selectedAoi.name}</h2>
                  <p style={{ fontSize: "13px", color: "var(--text-secondary)", marginTop: "4px", maxWidth: "800px" }}>
                    {selectedAoi.description}
                  </p>
                </div>
                <div
                  style={{
                    padding: "6px 12px",
                    borderRadius: "6px",
                    backgroundColor: "rgba(6, 182, 212, 0.1)",
                    border: "1px solid rgba(6, 182, 212, 0.3)",
                    fontSize: "12px",
                    color: "var(--accent-cyan)",
                    fontWeight: 600,
                  }}
                >
                  {selectedAoi.area_hectares.toLocaleString()} Hectares
                </div>
              </div>

              {/* Geographic Coordinates & Metadata Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginTop: "16px" }}>
                <div style={{ backgroundColor: "var(--bg-surface)", padding: "12px", borderRadius: "6px", border: "1px solid var(--border-color)" }}>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Bounding Box (Lon/Lat)</div>
                  <div style={{ fontSize: "12px", fontFamily: "var(--font-mono)", marginTop: "4px", color: "var(--text-primary)" }}>
                    [{selectedAoi.bounding_box.min_lon}, {selectedAoi.bounding_box.min_lat}] to [{selectedAoi.bounding_box.max_lon}, {selectedAoi.bounding_box.max_lat}]
                  </div>
                </div>

                <div style={{ backgroundColor: "var(--bg-surface)", padding: "12px", borderRadius: "6px", border: "1px solid var(--border-color)" }}>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Spatial Reference (CRS)</div>
                  <div style={{ fontSize: "12px", fontFamily: "var(--font-mono)", marginTop: "4px", color: "var(--text-primary)" }}>
                    EPSG:4326 (WGS84)
                  </div>
                </div>

                <div style={{ backgroundColor: "var(--bg-surface)", padding: "12px", borderRadius: "6px", border: "1px solid var(--border-color)" }}>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Cataloged Scenes</div>
                  <div style={{ fontSize: "12px", fontFamily: "var(--font-mono)", marginTop: "4px", color: "var(--accent-cyan)" }}>
                    {scenes.length} Sentinel-2 Scenes
                  </div>
                </div>

                <div style={{ backgroundColor: "var(--bg-surface)", padding: "12px", borderRadius: "6px", border: "1px solid var(--border-color)" }}>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Spatial Infrastructure</div>
                  <div style={{ fontSize: "12px", fontFamily: "var(--font-mono)", marginTop: "4px", color: "var(--accent-emerald)" }}>
                    {infra?.features?.length || 0} Features Indexed
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Architecture Roadmap Grid */}
          <div
            style={{
              backgroundColor: "var(--bg-secondary)",
              borderRadius: "8px",
              border: "1px solid var(--border-color)",
              padding: "20px",
            }}
          >
            <h3 style={{ fontSize: "15px", fontWeight: 600, marginBottom: "16px", color: "var(--text-primary)" }}>
              TerraLens GIS & AI Agent Architecture Roadmap
            </h3>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "14px" }}>
              <div
                style={{
                  padding: "14px",
                  borderRadius: "6px",
                  backgroundColor: "rgba(16, 185, 129, 0.06)",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--accent-emerald)", fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>
                  <CheckCircle2 size={16} />
                  <span>Phase 1: Foundation</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  PostgreSQL + PostGIS database schema, GIST spatial indexes, documented study area seed datasets, georeferenced Sentinel-2 GeoTIFFs, and FastAPI REST endpoints.
                </div>
              </div>

              <div
                style={{
                  padding: "14px",
                  borderRadius: "6px",
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-color)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--accent-cyan)", fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>
                  <Radio size={16} />
                  <span>Phase 2: Raster & NDVI</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  Deterministic Rasterio/NumPy NDVI calculation, temporal differencing, radiometric quality checks, and change mask thresholding.
                </div>
              </div>

              <div
                style={{
                  padding: "14px",
                  borderRadius: "6px",
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-color)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--text-muted)", fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>
                  <Layers size={16} />
                  <span>Phase 3: Vector & PostGIS</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  Raster-to-vector polygon conversion, Shapely polygon smoothing, PostGIS spatial persistence, and infrastructure proximity overlay.
                </div>
              </div>

              <div
                style={{
                  padding: "14px",
                  borderRadius: "6px",
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-color)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--text-muted)", fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>
                  <ShieldCheck size={16} />
                  <span>Phase 4: Agent & Quality Gate</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  LLM tool-calling agent orchestrating GIS tools, quality validation gate (cloud cover, min area, min delta), and concise user-facing activity logs.
                </div>
              </div>

              <div
                style={{
                  padding: "14px",
                  borderRadius: "6px",
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-color)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--text-muted)", fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>
                  <MapPin size={16} />
                  <span>Phase 5: Interactive Map</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  Full MapLibre GL visualization with satellite basemap, vector change polygons, infrastructure markers, and polygon click statistics.
                </div>
              </div>

              <div
                style={{
                  padding: "14px",
                  borderRadius: "6px",
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-color)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--text-muted)", fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>
                  <Activity size={16} />
                  <span>Phase 6: Verification & Tests</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  Automated test suites (valid change, high-cloud rejection, stable forest, invalid geom), error handling, and end-to-end demo workflows.
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
