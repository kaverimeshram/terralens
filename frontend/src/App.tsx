import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  Activity,
  Satellite,
  Database,
  ExternalLink,
  Play,
} from "lucide-react";
import {
  fetchHealth,
  fetchAOIs,
  fetchAOIScenes,
  fetchAOIInfrastructure,
  runNDVIAnalysis,
  fetchAnalysisChanges,
  fetchAnalysisRuns,
  fetchAnalysisSpatialSummary,
  fetchAnalysisNearbyInfrastructure,
  fetchAnalysisPopulationContext,
} from "./services/api";
import {
  AOI,
  GeoJSONFeatureCollection,
  HealthStatus,
  SatelliteScene,
  AnalysisRun,
  NearbyInfrastructureResponse,
  SpatialSummaryResponse,
  PopulationContextResponse,
} from "./types";

const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [aois, setAois] = useState<AOI[]>([]);
  const [selectedAoi, setSelectedAoi] = useState<AOI | null>(null);
  const [scenes, setScenes] = useState<SatelliteScene[]>([]);
  const [beforeSceneId, setBeforeSceneId] = useState<string>("");
  const [afterSceneId, setAfterSceneId] = useState<string>("");
  const [threshold, setThreshold] = useState<number>(-0.2);

  // Analysis & Spatial Intelligence State
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [analysisRuns, setAnalysisRuns] = useState<AnalysisRun[]>([]);
  const [activeAnalysisId, setActiveAnalysisId] = useState<string | null>(null);
  const [changePolygons, setChangePolygons] = useState<GeoJSONFeatureCollection | null>(null);
  const [allInfra, setAllInfra] = useState<GeoJSONFeatureCollection | null>(null);

  // Phase 3 Proximity & PostGIS Results
  const [radiusM, setRadiusM] = useState<number>(1000);
  const [nearbyInfra, setNearbyInfra] = useState<NearbyInfrastructureResponse | null>(null);
  const [spatialSummary, setSpatialSummary] = useState<SpatialSummaryResponse | null>(null);
  const [popContext, setPopContext] = useState<PopulationContextResponse | null>(null);

  // UI State
  const [activeTab, setActiveTab] = useState<"analysis" | "spatial" | "population" | "scenes">("analysis");
  const [selectedFeatureInfo, setSelectedFeatureInfo] = useState<any | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // MapLibre Ref
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const activePopup = useRef<maplibregl.Popup | null>(null);

  // Load initial AOIs and health
  useEffect(() => {
    loadInitialData();
  }, []);

  // Initialize MapLibre GL
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: MAP_STYLE,
      center: [35.885, -0.385],
      zoom: 11,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: "TerraLens PostGIS Spatial Engine",
      }),
      "bottom-right"
    );

    map.on("load", () => {
      setupMapLayers(map);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Sync AOI Selection & Scenes
  useEffect(() => {
    if (!selectedAoi) return;
    loadAoiDetails(selectedAoi);
  }, [selectedAoi]);

  // Update Proximity Queries when radius or active analysis changes
  useEffect(() => {
    if (!activeAnalysisId) return;
    loadSpatialData(activeAnalysisId, radiusM);
  }, [activeAnalysisId, radiusM]);

  // Update Map Layers when data changes
  useEffect(() => {
    updateMapData();
  }, [selectedAoi, changePolygons, nearbyInfra, allInfra, popContext]);

  async function loadInitialData() {
    try {
      const [healthData, aoisGeo, runs] = await Promise.all([
        fetchHealth().catch(() => null),
        fetchAOIs(),
        fetchAnalysisRuns().catch(() => []),
      ]);

      if (healthData) setHealth(healthData);
      setAnalysisRuns(runs);

      const aoiList = aoisGeo.features.map((f) => ({
        ...f.properties,
        geometry: f.geometry,
      }));
      setAois(aoiList);

      if (aoiList.length > 0) {
        setSelectedAoi(aoiList[0]);
      }
    } catch (err) {
      console.error("Initialization error:", err);
    }
  }

  async function loadAoiDetails(aoi: AOI) {
    try {
      const [scenesData, infraData, runs] = await Promise.all([
        fetchAOIScenes(aoi.id),
        fetchAOIInfrastructure(aoi.id),
        fetchAnalysisRuns().catch(() => []),
      ]);

      setScenes(scenesData);
      setAllInfra(infraData);
      setAnalysisRuns(runs);

      // Auto-select first two scenes for comparison if available
      if (scenesData.length >= 2) {
        setBeforeSceneId(scenesData[0].id);
        setAfterSceneId(scenesData[1].id);
      }

      // Check if an existing analysis matches this AOI
      const matchingRun = runs.find((r) => r.aoi_id === aoi.id);
      if (matchingRun) {
        selectAnalysisRun(matchingRun.id);
      } else {
        setActiveAnalysisId(null);
        setChangePolygons(null);
        setNearbyInfra(null);
        setSpatialSummary(null);
        setPopContext(null);
      }

      // Fit map to AOI bounds
      if (mapRef.current && aoi.bounding_box) {
        const bbox = aoi.bounding_box;
        mapRef.current.fitBounds(
          [
            [bbox.min_lon, bbox.min_lat],
            [bbox.max_lon, bbox.max_lat],
          ],
          { padding: 40, duration: 1000 }
        );
      }
    } catch (err) {
      console.error("Failed to load AOI details:", err);
    }
  }

  async function selectAnalysisRun(analysisId: string) {
    setActiveAnalysisId(analysisId);
    setStatusMessage("Loading PostGIS change polygons & spatial relationships...");
    try {
      const [changes, summary, proximity, population] = await Promise.all([
        fetchAnalysisChanges(analysisId),
        fetchAnalysisSpatialSummary(analysisId, radiusM),
        fetchAnalysisNearbyInfrastructure(analysisId, radiusM, "json") as Promise<NearbyInfrastructureResponse>,
        fetchAnalysisPopulationContext(analysisId, radiusM, "json") as Promise<PopulationContextResponse>,
      ]);

      setChangePolygons(changes);
      setSpatialSummary(summary);
      setNearbyInfra(proximity);
      setPopContext(population);
      setStatusMessage(null);

      // Fit map to changes if available
      if (mapRef.current && changes.features.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        changes.features.forEach((f) => {
          if (f.geometry.type === "Polygon") {
            f.geometry.coordinates[0].forEach((c: [number, number]) => bounds.extend(c));
          } else if (f.geometry.type === "MultiPolygon") {
            f.geometry.coordinates.forEach((p: any) =>
              p[0].forEach((c: [number, number]) => bounds.extend(c))
            );
          }
        });
        if (!bounds.isEmpty()) {
          mapRef.current.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 800 });
        }
      }
    } catch (err: any) {
      console.error("Error loading analysis data:", err);
      setStatusMessage(`Error: ${err.message || "Failed to load spatial data"}`);
    }
  }

  async function loadSpatialData(analysisId: string, radius: number) {
    try {
      const [summary, proximity, population] = await Promise.all([
        fetchAnalysisSpatialSummary(analysisId, radius),
        fetchAnalysisNearbyInfrastructure(analysisId, radius, "json") as Promise<NearbyInfrastructureResponse>,
        fetchAnalysisPopulationContext(analysisId, radius, "json") as Promise<PopulationContextResponse>,
      ]);
      setSpatialSummary(summary);
      setNearbyInfra(proximity);
      setPopContext(population);
    } catch (err) {
      console.error("Error updating spatial proximity:", err);
    }
  }

  async function handleRunAnalysis() {
    if (!selectedAoi || !beforeSceneId || !afterSceneId) return;

    setIsAnalyzing(true);
    setStatusMessage("Executing deterministic NDVI difference & PostGIS vectorization...");
    try {
      const result = await runNDVIAnalysis({
        aoi_id: selectedAoi.id,
        before_scene_id: beforeSceneId,
        after_scene_id: afterSceneId,
        threshold: threshold,
        minimum_area_m2: 500.0,
      });

      const newRuns = await fetchAnalysisRuns();
      setAnalysisRuns(newRuns);
      await selectAnalysisRun(result.analysis_id);
      setActiveTab("spatial");
      setStatusMessage(null);
    } catch (err: any) {
      console.error("Analysis execution failed:", err);
      setStatusMessage(`Analysis error: ${err.message}`);
    } finally {
      setIsAnalyzing(false);
    }
  }

  function setupMapLayers(map: maplibregl.Map) {
    // 1. AOI Boundary Source & Layer
    map.addSource("aoi-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addLayer({
      id: "aoi-fill",
      type: "fill",
      source: "aoi-source",
      paint: {
        "fill-color": "#06b6d4",
        "fill-opacity": 0.04,
      },
    });
    map.addLayer({
      id: "aoi-outline",
      type: "line",
      source: "aoi-source",
      paint: {
        "line-color": "#06b6d4",
        "line-width": 2,
        "line-dasharray": [2, 2],
      },
    });

    // 2. Population Zones Source & Layer
    map.addSource("pop-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addLayer({
      id: "pop-fill",
      type: "fill",
      source: "pop-source",
      paint: {
        "fill-color": "#6366f1",
        "fill-opacity": 0.12,
      },
    });
    map.addLayer({
      id: "pop-outline",
      type: "line",
      source: "pop-source",
      paint: {
        "line-color": "#6366f1",
        "line-width": 1.5,
        "line-dasharray": [3, 2],
      },
    });

    // 3. Change Polygons Source & Layer
    map.addSource("changes-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addLayer({
      id: "changes-fill",
      type: "fill",
      source: "changes-source",
      paint: {
        "fill-color": [
          "case",
          ["<=", ["get", "mean_ndvi_change"], -0.2],
          "#f43f5e",
          [">=", ["get", "mean_ndvi_change"], 0.2],
          "#10b981",
          "#f59e0b",
        ],
        "fill-opacity": 0.55,
      },
    });
    map.addLayer({
      id: "changes-line",
      type: "line",
      source: "changes-source",
      paint: {
        "line-color": [
          "case",
          ["<=", ["get", "mean_ndvi_change"], -0.2],
          "#fda4af",
          "#6ee7b7",
        ],
        "line-width": 1.5,
      },
    });

    // 4. Infrastructure Source & Layers (Points & Lines)
    map.addSource("infra-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: "infra-lines",
      type: "line",
      source: "infra-source",
      filter: ["==", "$type", "LineString"],
      paint: {
        "line-color": "#38bdf8",
        "line-width": 3.5,
      },
    });

    map.addLayer({
      id: "infra-points-halo",
      type: "circle",
      source: "infra-source",
      filter: ["==", "$type", "Point"],
      paint: {
        "circle-radius": 9,
        "circle-color": "rgba(56, 189, 248, 0.25)",
        "circle-stroke-width": 1,
        "circle-stroke-color": "#38bdf8",
      },
    });

    map.addLayer({
      id: "infra-points",
      type: "circle",
      source: "infra-source",
      filter: ["==", "$type", "Point"],
      paint: {
        "circle-radius": 5,
        "circle-color": "#38bdf8",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
      },
    });

    // Layer Click & Hover Interactions
    map.on("click", "changes-fill", (e) => {
      if (!e.features || e.features.length === 0) return;
      const feat = e.features[0];
      const props = feat.properties || {};

      setSelectedFeatureInfo({
        category: "Change Polygon",
        ...props,
      });

      if (activePopup.current) activePopup.current.remove();

      const htmlContent = `
        <div style="font-family: var(--font-sans); padding: 4px; color: #f8fafc;">
          <div style="font-size: 11px; font-weight: 700; color: #f43f5e; text-transform: uppercase; margin-bottom: 4px;">
            ${props.change_type || "Detected Vegetation Decrease"}
          </div>
          <div style="font-size: 12px; margin-bottom: 2px;">
            Area: <strong>${Number(props.area_ha || 0).toFixed(2)} ha</strong> (${Number(props.area_m2 || 0).toLocaleString()} m²)
          </div>
          <div style="font-size: 12px; margin-bottom: 2px;">
            Δ NDVI: <strong style="color: #f43f5e;">${Number(props.mean_ndvi_change || 0).toFixed(4)}</strong>
          </div>
          ${props.mean_before_ndvi !== undefined ? `<div style="font-size: 11px; color: #94a3b8;">Before: ${Number(props.mean_before_ndvi).toFixed(3)} | After: ${Number(props.mean_after_ndvi).toFixed(3)}</div>` : ""}
        </div>
      `;

      activePopup.current = new maplibregl.Popup({ className: "terralens-popup", closeButton: false })
        .setLngLat(e.lngLat)
        .setHTML(htmlContent)
        .addTo(map);
    });

    map.on("click", "infra-points", (e) => {
      if (!e.features || e.features.length === 0) return;
      const feat = e.features[0];
      const props = feat.properties || {};

      setSelectedFeatureInfo({
        category: "Infrastructure",
        ...props,
      });

      if (activePopup.current) activePopup.current.remove();

      const distStr =
        props.distance_m !== undefined
          ? props.distance_m === 0
            ? "0.0 m (Directly Intersects)"
            : `${Number(props.distance_m).toFixed(1)} m from change`
          : "Mapped Asset";

      const htmlContent = `
        <div style="font-family: var(--font-sans); padding: 4px; color: #f8fafc;">
          <div style="font-size: 11px; font-weight: 700; color: #38bdf8; text-transform: uppercase; margin-bottom: 2px;">
            ${props.type || "Infrastructure"}
          </div>
          <div style="font-size: 13px; font-weight: 600; margin-bottom: 4px;">
            ${props.name}
          </div>
          <div style="font-size: 12px; color: #10b981; font-weight: 500;">
            PostGIS Proximity: <strong>${distStr}</strong>
          </div>
        </div>
      `;

      activePopup.current = new maplibregl.Popup({ className: "terralens-popup", closeButton: false })
        .setLngLat(e.lngLat)
        .setHTML(htmlContent)
        .addTo(map);
    });

    map.on("mouseenter", "changes-fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "changes-fill", () => (map.getCanvas().style.cursor = ""));
    map.on("mouseenter", "infra-points", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "infra-points", () => (map.getCanvas().style.cursor = ""));
  }

  function updateMapData() {
    if (!mapRef.current) return;
    const map = mapRef.current;
    if (!map.isStyleLoaded()) return;

    // Update AOI
    const aoiSource = map.getSource("aoi-source") as maplibregl.GeoJSONSource;
    if (aoiSource) {
      if (selectedAoi?.geometry) {
        aoiSource.setData({
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: selectedAoi.geometry,
              properties: { name: selectedAoi.name },
            },
          ],
        });
      } else {
        aoiSource.setData({ type: "FeatureCollection", features: [] });
      }
    }

    // Update Change Polygons
    const changesSource = map.getSource("changes-source") as maplibregl.GeoJSONSource;
    if (changesSource) {
      changesSource.setData(changePolygons || { type: "FeatureCollection", features: [] });
    }

    // Update Infrastructure
    const infraSource = map.getSource("infra-source") as maplibregl.GeoJSONSource;
    if (infraSource) {
      if (nearbyInfra && nearbyInfra.infrastructure.length > 0) {
        const features = nearbyInfra.infrastructure
          .filter((item) => item.geometry)
          .map((item) => ({
            type: "Feature" as const,
            id: item.id,
            geometry: item.geometry,
            properties: {
              id: item.id,
              name: item.name,
              type: item.type,
              distance_m: item.distance_m,
              nearest_change_polygon_id: item.nearest_change_polygon_id,
            },
          }));
        infraSource.setData({ type: "FeatureCollection", features });
      } else if (allInfra) {
        infraSource.setData(allInfra);
      } else {
        infraSource.setData({ type: "FeatureCollection", features: [] });
      }
    }

    // Update Population Zones
    const popSource = map.getSource("pop-source") as maplibregl.GeoJSONSource;
    if (popSource) {
      if (popContext && popContext.zones.length > 0) {
        const features = popContext.zones
          .filter((z) => z.geometry)
          .map((z) => ({
            type: "Feature" as const,
            id: z.id,
            geometry: z.geometry,
            properties: {
              id: z.id,
              name: z.name,
              population: z.population,
              distance_m: z.distance_m,
              intersects_change: z.intersects_change,
            },
          }));
        popSource.setData({ type: "FeatureCollection", features });
      } else {
        popSource.setData({ type: "FeatureCollection", features: [] });
      }
    }
  }

  function flyToFeature(geom: any) {
    if (!mapRef.current || !geom) return;
    if (geom.type === "Point") {
      mapRef.current.flyTo({
        center: geom.coordinates,
        zoom: 14,
        duration: 800,
      });
    } else if (geom.type === "LineString") {
      const bounds = new maplibregl.LngLatBounds();
      geom.coordinates.forEach((c: [number, number]) => bounds.extend(c));
      mapRef.current.fitBounds(bounds, { padding: 60, duration: 800 });
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
          zIndex: 10,
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
                  backgroundColor: "rgba(6, 182, 212, 0.15)",
                  color: "var(--accent-cyan)",
                  border: "1px solid rgba(6, 182, 212, 0.3)",
                }}
              >
                PHASE 3: SPATIAL INTELLIGENCE
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              PostGIS Spatial Intelligence & Remote Sensing Change Analysis Engine
            </div>
          </div>
        </div>

        {/* Status Badges */}
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
            <span>{health?.database?.connected ? "PostGIS Spatial Engine Online" : "PostGIS Offline"}</span>
          </div>

          <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
            <span style={{ color: "var(--text-muted)" }}>Analysis Runs: </span>
            <strong style={{ color: "var(--text-primary)" }}>{analysisRuns.length}</strong>
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

      {/* Main Workspace Layout */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "390px 1fr", overflow: "hidden" }}>
        {/* Left Sidebar: Controls & PostGIS Results */}
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
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border-color)" }}>
            <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "1px", color: "var(--text-muted)", marginBottom: "8px", fontWeight: 600 }}>
              Study Area (AOI)
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              {aois.map((aoi) => {
                const isSelected = selectedAoi?.id === aoi.id;
                return (
                  <button
                    key={aoi.id}
                    onClick={() => setSelectedAoi(aoi)}
                    style={{
                      flex: 1,
                      textAlign: "left",
                      padding: "8px 10px",
                      borderRadius: "6px",
                      backgroundColor: isSelected ? "var(--bg-surface)" : "transparent",
                      border: `1px solid ${isSelected ? "var(--border-focus)" : "var(--border-subtle)"}`,
                      color: isSelected ? "var(--text-primary)" : "var(--text-secondary)",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: "12px", color: isSelected ? "var(--accent-cyan)" : "var(--text-primary)", marginBottom: "2px" }}>
                      {aoi.name.split(" ")[0]}...
                    </div>
                    <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                      {aoi.area_hectares.toLocaleString()} ha
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Navigation Tabs */}
          <div style={{ display: "flex", borderBottom: "1px solid var(--border-color)", backgroundColor: "var(--bg-primary)" }}>
            <button
              onClick={() => setActiveTab("analysis")}
              style={{
                flex: 1,
                padding: "9px 0",
                fontSize: "11px",
                fontWeight: 600,
                background: "none",
                border: "none",
                borderBottom: activeTab === "analysis" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "analysis" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              NDVI Change
            </button>
            <button
              onClick={() => setActiveTab("spatial")}
              style={{
                flex: 1,
                padding: "9px 0",
                fontSize: "11px",
                fontWeight: 600,
                background: "none",
                border: "none",
                borderBottom: activeTab === "spatial" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "spatial" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              Proximity ({nearbyInfra?.infrastructure_count ?? 0})
            </button>
            <button
              onClick={() => setActiveTab("population")}
              style={{
                flex: 1,
                padding: "9px 0",
                fontSize: "11px",
                fontWeight: 600,
                background: "none",
                border: "none",
                borderBottom: activeTab === "population" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "population" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              Population
            </button>
            <button
              onClick={() => setActiveTab("scenes")}
              style={{
                flex: 1,
                padding: "9px 0",
                fontSize: "11px",
                fontWeight: 600,
                background: "none",
                border: "none",
                borderBottom: activeTab === "scenes" ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                color: activeTab === "scenes" ? "var(--accent-cyan)" : "var(--text-muted)",
                cursor: "pointer",
              }}
            >
              Catalog
            </button>
          </div>

          {/* Tab Content Container */}
          <div style={{ flex: 1, padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "14px" }}>
            {/* Status / Loading Notification */}
            {statusMessage && (
              <div
                style={{
                  padding: "8px 12px",
                  borderRadius: "6px",
                  backgroundColor: "rgba(6, 182, 212, 0.1)",
                  border: "1px solid rgba(6, 182, 212, 0.3)",
                  fontSize: "11px",
                  color: "var(--accent-cyan)",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                }}
              >
                <Activity size={14} className="animate-spin" />
                <span>{statusMessage}</span>
              </div>
            )}

            {/* TAB 1: NDVI Change Analysis Configuration */}
            {activeTab === "analysis" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-primary)" }}>
                  Deterministic Remote Sensing Setup
                </div>

                {/* Baseline Scene */}
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                    Baseline Scene (Before)
                  </label>
                  <select
                    value={beforeSceneId}
                    onChange={(e) => setBeforeSceneId(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      color: "var(--text-primary)",
                      fontSize: "12px",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {scenes.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.acquisition_date} - {s.scene_identifier.slice(0, 24)}... ({s.cloud_cover}% cloud)
                      </option>
                    ))}
                  </select>
                </div>

                {/* Comparison Scene */}
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                    Comparison Scene (After)
                  </label>
                  <select
                    value={afterSceneId}
                    onChange={(e) => setAfterSceneId(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      color: "var(--text-primary)",
                      fontSize: "12px",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {scenes.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.acquisition_date} - {s.scene_identifier.slice(0, 24)}... ({s.cloud_cover}% cloud)
                      </option>
                    ))}
                  </select>
                </div>

                {/* Threshold */}
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                    <span style={{ color: "var(--text-muted)" }}>NDVI Decrease Threshold:</span>
                    <strong style={{ color: "var(--accent-rose)", fontFamily: "var(--font-mono)" }}>{threshold.toFixed(2)}</strong>
                  </div>
                  <input
                    type="range"
                    min="-0.40"
                    max="-0.05"
                    step="0.01"
                    value={threshold}
                    onChange={(e) => setThreshold(parseFloat(e.target.value))}
                    style={{ width: "100%", accentColor: "var(--accent-rose)" }}
                  />
                  <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px" }}>
                    Pixels where Δ NDVI ≤ {threshold.toFixed(2)} are vectorized as potential vegetation loss.
                  </div>
                </div>

                {/* Execute Button */}
                <button
                  onClick={handleRunAnalysis}
                  disabled={isAnalyzing || !beforeSceneId || !afterSceneId}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    padding: "10px",
                    borderRadius: "6px",
                    backgroundColor: "var(--accent-cyan)",
                    color: "#0a0d14",
                    fontWeight: 600,
                    fontSize: "13px",
                    border: "none",
                    cursor: isAnalyzing ? "not-allowed" : "pointer",
                    opacity: isAnalyzing ? 0.7 : 1,
                    transition: "opacity 0.2s",
                  }}
                >
                  <Play size={16} />
                  <span>{isAnalyzing ? "Processing Analysis..." : "Execute Spatial Analysis"}</span>
                </button>

                {/* Analysis Execution Metrics Summary */}
                {spatialSummary && (
                  <div
                    style={{
                      padding: "12px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      marginTop: "6px",
                    }}
                  >
                    <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "8px" }}>
                      Detected Vegetation Change
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "12px" }}>
                      <div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>Total Area</div>
                        <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--accent-rose)" }}>
                          {spatialSummary.change_metrics.total_change_area_ha.toFixed(2)} ha
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>Change Polygons</div>
                        <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--text-primary)" }}>
                          {spatialSummary.change_metrics.change_polygon_count}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>Mean Δ NDVI</div>
                        <div style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--accent-rose)" }}>
                          {spatialSummary.change_metrics.mean_ndvi_change.toFixed(4)}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>AOI Containment</div>
                        <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-emerald)" }}>
                          {spatialSummary.aoi_containment.all_contained ? "✓ 100% Contained" : "Partial"}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: PostGIS Proximity Analysis & Nearby Infrastructure */}
            {activeTab === "spatial" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-primary)" }}>
                    PostGIS ST_DWithin Proximity Search
                  </div>
                </div>

                {/* Radius Buttons */}
                <div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", marginBottom: "6px" }}>
                    Proximity Search Radius (Meters):
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "6px" }}>
                    {[500, 1000, 2000, 5000].map((r) => (
                      <button
                        key={r}
                        onClick={() => setRadiusM(r)}
                        style={{
                          padding: "6px 0",
                          borderRadius: "4px",
                          fontSize: "11px",
                          fontWeight: 600,
                          backgroundColor: radiusM === r ? "var(--accent-cyan)" : "var(--bg-surface)",
                          color: radiusM === r ? "#0a0d14" : "var(--text-secondary)",
                          border: `1px solid ${radiusM === r ? "var(--accent-cyan)" : "var(--border-color)"}`,
                          cursor: "pointer",
                        }}
                      >
                        {r >= 1000 ? `${r / 1000} km` : `${r} m`}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Proximity Summary Banner */}
                {nearbyInfra && (
                  <div
                    style={{
                      padding: "10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      fontSize: "11px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ color: "var(--text-muted)" }}>Infrastructure in Radius:</span>
                      <strong style={{ color: "var(--accent-cyan)" }}>{nearbyInfra.infrastructure_count} assets</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "var(--text-muted)" }}>Associated Change Area:</span>
                      <strong style={{ color: "var(--accent-rose)" }}>{nearbyInfra.associated_change_area_ha.toFixed(2)} ha</strong>
                    </div>
                  </div>
                )}

                {/* Infrastructure List Sorted by Distance */}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {nearbyInfra?.infrastructure.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => flyToFeature(item.geometry)}
                      style={{
                        padding: "10px",
                        borderRadius: "6px",
                        backgroundColor: "var(--bg-surface)",
                        border: "1px solid var(--border-color)",
                        cursor: "pointer",
                        transition: "border-color 0.15s ease",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "4px" }}>
                        <span style={{ fontWeight: 600, fontSize: "12px", color: "var(--text-primary)" }}>{item.name}</span>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            fontFamily: "var(--font-mono)",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            backgroundColor: item.distance_m === 0 ? "rgba(244, 63, 94, 0.15)" : "rgba(16, 185, 129, 0.15)",
                            color: item.distance_m === 0 ? "var(--accent-rose)" : "var(--accent-emerald)",
                            border: `1px solid ${item.distance_m === 0 ? "rgba(244, 63, 94, 0.3)" : "rgba(16, 185, 129, 0.3)"}`,
                          }}
                        >
                          {item.distance_m === 0 ? "0 m (Intersects)" : `${item.distance_m.toFixed(1)} m`}
                        </span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted)" }}>
                        <span style={{ color: "var(--accent-cyan)" }}>{item.type}</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>Poly: {item.nearest_change_polygon_id.slice(0, 8)}...</span>
                      </div>
                    </div>
                  ))}

                  {nearbyInfra?.infrastructure.length === 0 && (
                    <div style={{ padding: "16px", textAlign: "center", color: "var(--text-muted)", fontSize: "12px" }}>
                      No infrastructure assets within {radiusM} m of detected vegetation change polygons.
                    </div>
                  )}
                </div>

                {/* Factual Statements Card */}
                {nearbyInfra?.factual_summary && nearbyInfra.factual_summary.length > 0 && (
                  <div
                    style={{
                      padding: "10px 12px",
                      borderRadius: "6px",
                      backgroundColor: "rgba(16, 185, 129, 0.05)",
                      border: "1px solid rgba(16, 185, 129, 0.2)",
                      fontSize: "11px",
                      color: "var(--text-secondary)",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "var(--accent-emerald)", marginBottom: "4px" }}>
                      PostGIS Factual Summary:
                    </div>
                    {nearbyInfra.factual_summary.map((stmt, idx) => (
                      <div key={idx} style={{ marginBottom: "2px" }}>
                        • {stmt}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: Population Zone Demographic Context */}
            {activeTab === "population" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-primary)" }}>
                  Population Zones & Demographic Proximity
                </div>

                {popContext && (
                  <div
                    style={{
                      padding: "10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      fontSize: "11px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ color: "var(--text-muted)" }}>Zones in Radius:</span>
                      <strong style={{ color: "var(--accent-indigo)" }}>{popContext.population_zones_count}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ color: "var(--text-muted)" }}>Intersecting Zones:</span>
                      <strong style={{ color: popContext.intersecting_zones_count > 0 ? "var(--accent-rose)" : "var(--accent-emerald)" }}>
                        {popContext.intersecting_zones_count}
                      </strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "var(--text-muted)" }}>Registered Population:</span>
                      <strong style={{ color: "var(--text-primary)" }}>{popContext.total_intersecting_population.toLocaleString()}</strong>
                    </div>
                  </div>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {popContext?.zones.map((zone) => (
                    <div
                      key={zone.id}
                      onClick={() => flyToFeature(zone.geometry)}
                      style={{
                        padding: "10px",
                        borderRadius: "6px",
                        backgroundColor: "var(--bg-surface)",
                        border: "1px solid var(--border-color)",
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                        <span style={{ fontWeight: 600, fontSize: "12px" }}>{zone.name}</span>
                        <span style={{ fontSize: "11px", color: "var(--accent-indigo)", fontWeight: 600 }}>
                          Pop: {zone.population.toLocaleString()}
                        </span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted)" }}>
                        <span>Zone Area: {zone.zone_area_ha.toFixed(1)} ha</span>
                        <span style={{ color: zone.intersects_change ? "var(--accent-rose)" : "var(--text-secondary)" }}>
                          {zone.intersects_change ? `Intersects (${zone.intersection_area_ha.toFixed(2)} ha)` : `${zone.distance_m.toFixed(0)} m away`}
                        </span>
                      </div>
                    </div>
                  ))}

                  {popContext?.zones.length === 0 && (
                    <div style={{ padding: "16px", textAlign: "center", color: "var(--text-muted)", fontSize: "12px" }}>
                      No population zones identified within {radiusM} m of change polygons.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 4: Scene Catalog */}
            {activeTab === "scenes" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {scenes.map((scene) => (
                  <div
                    key={scene.id}
                    style={{
                      padding: "10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-color)",
                      fontSize: "11px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
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
                    <div style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)", fontSize: "10px", marginBottom: "4px" }}>
                      {scene.scene_identifier}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text-secondary)" }}>
                      <span>Acquired: {scene.acquisition_date}</span>
                      <span>Res: {scene.spatial_resolution}m</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Right Main Panel: Interactive MapLibre GL Visualization */}
        <main style={{ position: "relative", width: "100%", height: "100%" }}>
          <div ref={mapContainer} style={{ width: "100%", height: "100%" }} />

          {/* Map Floating Legend */}
          <div
            style={{
              position: "absolute",
              bottom: "24px",
              left: "24px",
              backgroundColor: "rgba(17, 23, 34, 0.92)",
              backdropFilter: "blur(8px)",
              border: "1px solid var(--border-color)",
              borderRadius: "8px",
              padding: "12px 14px",
              fontSize: "11px",
              zIndex: 5,
              display: "flex",
              flexDirection: "column",
              gap: "8px",
              minWidth: "220px",
            }}
          >
            <div style={{ fontWeight: 700, fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-primary)" }}>
              Spatial Layer Legend
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "12px", height: "12px", borderRadius: "2px", backgroundColor: "#f43f5e", border: "1px solid #fda4af" }} />
              <span>Vegetation Decrease (ΔNDVI ≤ {threshold.toFixed(2)})</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#38bdf8", border: "2px solid #ffffff" }} />
              <span>Infrastructure Assets (PostGIS Indexed)</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "14px", height: "0px", borderTop: "3px solid #38bdf8" }} />
              <span>Road / Transport Corridor</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "12px", height: "12px", borderRadius: "2px", backgroundColor: "rgba(99, 102, 241, 0.2)", border: "1px dashed #6366f1" }} />
              <span>Population Zones</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "14px", height: "0px", borderTop: "2px dashed #06b6d4" }} />
              <span>AOI Boundary (EPSG:4326)</span>
            </div>
          </div>

          {/* Floating Selected Feature Inspector Card */}
          {selectedFeatureInfo && (
            <div
              style={{
                position: "absolute",
                top: "20px",
                right: "20px",
                backgroundColor: "rgba(17, 23, 34, 0.95)",
                backdropFilter: "blur(10px)",
                border: "1px solid var(--border-color)",
                borderRadius: "8px",
                padding: "14px 16px",
                fontSize: "12px",
                maxWidth: "320px",
                zIndex: 5,
                boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.5)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", color: "var(--accent-cyan)" }}>
                  {selectedFeatureInfo.category}
                </span>
                <button
                  onClick={() => setSelectedFeatureInfo(null)}
                  style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "14px" }}
                >
                  ✕
                </button>
              </div>

              {selectedFeatureInfo.category === "Change Polygon" ? (
                <div>
                  <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--accent-rose)", marginBottom: "4px" }}>
                    {selectedFeatureInfo.change_type}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "8px", fontSize: "11px" }}>
                    <div>Area: <strong>{Number(selectedFeatureInfo.area_ha || 0).toFixed(2)} ha</strong></div>
                    <div>Δ NDVI: <strong style={{ color: "var(--accent-rose)" }}>{Number(selectedFeatureInfo.mean_ndvi_change || 0).toFixed(4)}</strong></div>
                  </div>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--text-primary)", marginBottom: "2px" }}>
                    {selectedFeatureInfo.name}
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--accent-cyan)", marginBottom: "6px" }}>
                    Type: {selectedFeatureInfo.type}
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--accent-emerald)" }}>
                    Distance to Nearest Change: <strong>{selectedFeatureInfo.distance_m === 0 ? "0 m (Intersects)" : `${Number(selectedFeatureInfo.distance_m).toFixed(1)} m`}</strong>
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
