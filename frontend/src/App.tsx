import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  Activity,
  Satellite,
  Database,
  Play,
  Bot,
  Sparkles,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Layers,
  ShieldCheck,
  Terminal,
  MapPin,
  Users,
  Compass,
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
  runAgentAnalyze,
  fetchAgentHealth,
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
  AgentAnalyzeResponse,
  AgentHealthStatus,
} from "./types";

const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [agentHealth, setAgentHealth] = useState<AgentHealthStatus | null>(null);
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
  const [, setSpatialSummary] = useState<SpatialSummaryResponse | null>(null);
  const [popContext, setPopContext] = useState<PopulationContextResponse | null>(null);

  // Phase 4 Agent State
  const [agentQuery, setAgentQuery] = useState<string>(
    "Analyze vegetation change in Eastern Mau Forest between 2020 and 2025 and find nearby infrastructure within 1000m"
  );
  const [isAgentExecuting, setIsAgentExecuting] = useState<boolean>(false);
  const [agentResponse, setAgentResponse] = useState<AgentAnalyzeResponse | null>(null);

  // UI State
  const [activeTab, setActiveTab] = useState<"agent" | "analysis" | "spatial" | "population" | "scenes">("agent");
  const [selectedFeatureInfo, setSelectedFeatureInfo] = useState<any | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // MapLibre Ref
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

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
        customAttribution: "TerraLens Deterministic Spatial Agent",
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
      const [h, ah, aoisData, runs] = await Promise.all([
        fetchHealth().catch(() => null),
        fetchAgentHealth().catch(() => null),
        fetchAOIs().catch(() => ({ features: [] })),
        fetchAnalysisRuns().catch(() => []),
      ]);

      setHealth(h);
      setAgentHealth(ah);

      const parsedAois = (aoisData.features || []).map((f: any) => ({
        id: f.id || f.properties.id,
        name: f.properties.name,
        description: f.properties.description,
        bounding_box: f.properties.bounding_box,
        area_hectares: f.properties.area_hectares,
        created_at: f.properties.created_at,
        geometry: f.geometry,
      }));

      setAois(parsedAois);
      setAnalysisRuns(runs);

      if (parsedAois.length > 0) {
        setSelectedAoi(parsedAois[0]);
      }
    } catch (err: any) {
      setStatusMessage(`Initial data load error: ${err.message}`);
    }
  }

  async function loadAoiDetails(aoi: AOI) {
    try {
      const [sceneList, infraData] = await Promise.all([
        fetchAOIScenes(aoi.id),
        fetchAOIInfrastructure(aoi.id).catch(() => null),
      ]);

      setScenes(sceneList);
      setAllInfra(infraData);

      if (sceneList.length >= 2) {
        const clean = sceneList.filter(
          (s) => !s.scene_identifier.includes("STABLE") && !s.scene_identifier.includes("HIGHCLOUD")
        );
        setBeforeSceneId(clean[0]?.id || sceneList[0].id);
        setAfterSceneId(clean[clean.length - 1]?.id || sceneList[sceneList.length - 1].id);
      }

      if (mapRef.current && aoi.bounding_box) {
        mapRef.current.fitBounds(
          [
            [aoi.bounding_box.min_lon, aoi.bounding_box.min_lat],
            [aoi.bounding_box.max_lon, aoi.bounding_box.max_lat],
          ],
          { padding: 60, duration: 1200 }
        );
      }
    } catch (err: any) {
      setStatusMessage(`Error loading AOI scenes: ${err.message}`);
    }
  }

  async function loadSpatialData(analysisId: string, radius: number) {
    try {
      const [infra, summary, pop] = await Promise.all([
        fetchAnalysisNearbyInfrastructure(analysisId, radius, "json").catch(() => null),
        fetchAnalysisSpatialSummary(analysisId, radius).catch(() => null),
        fetchAnalysisPopulationContext(analysisId, radius, "json").catch(() => null),
      ]);

      setNearbyInfra(infra as NearbyInfrastructureResponse);
      setSpatialSummary(summary as SpatialSummaryResponse);
      setPopContext(pop as PopulationContextResponse);
    } catch (err: any) {
      setStatusMessage(`Error loading spatial summary: ${err.message}`);
    }
  }

  // --- Phase 4 AI Agent Execution Handler ---
  async function handleExecuteAgent() {
    if (!agentQuery || agentQuery.trim().length < 3) return;

    setIsAgentExecuting(true);
    setStatusMessage("Agent orchestrating: Resolving AOI -> Scenes -> Deterministic NDVI -> Quality Gate -> PostGIS Impact...");

    try {
      const resp: AgentAnalyzeResponse = await runAgentAnalyze({
        request: agentQuery,
        proximity_radius_m: radiusM,
        threshold: threshold,
      });

      setAgentResponse(resp);

      // If an analysis_id was generated/validated, load and sync the map layers
      if (resp.analysis_id) {
        setActiveAnalysisId(resp.analysis_id);

        // Fetch change polygons GeoJSON
        const changesGeoJSON = await fetchAnalysisChanges(resp.analysis_id).catch(() => null);
        if (changesGeoJSON) {
          setChangePolygons(changesGeoJSON);
        }

        // Sync AOI if returned
        if (resp.aoi_id) {
          const matchedAoi = aois.find((a) => a.id === resp.aoi_id);
          if (matchedAoi) {
            setSelectedAoi(matchedAoi);
          }
        }

        // Refresh analysis runs
        fetchAnalysisRuns().then(setAnalysisRuns).catch(() => {});
      }

      setStatusMessage(`Agent analysis completed with status: ${resp.status.toUpperCase()}`);
    } catch (err: any) {
      setStatusMessage(`Agent Error: ${err.message}`);
    } finally {
      setIsAgentExecuting(false);
    }
  }

  // --- Manual NDVI Trigger Handler ---
  async function handleRunNDVI() {
    if (!selectedAoi || !beforeSceneId || !afterSceneId) return;

    setIsAnalyzing(true);
    setStatusMessage("Executing deterministic NDVI band algebra & PostGIS vectorization...");

    try {
      const result = await runNDVIAnalysis({
        aoi_id: selectedAoi.id,
        before_scene_id: beforeSceneId,
        after_scene_id: afterSceneId,
        threshold: threshold,
        minimum_area_m2: 500,
      });

      setActiveAnalysisId(result.analysis_id);

      const changesGeoJSON = await fetchAnalysisChanges(result.analysis_id);
      setChangePolygons(changesGeoJSON);

      const updatedRuns = await fetchAnalysisRuns();
      setAnalysisRuns(updatedRuns);

      setStatusMessage(
        `NDVI change detection complete: ${result.metrics.total_change_area_ha} ha detected across ${result.metrics.change_polygon_count} polygon(s).`
      );
    } catch (err: any) {
      setStatusMessage(`Analysis error: ${err.message}`);
    } finally {
      setIsAnalyzing(false);
    }
  }

  function setupMapLayers(map: maplibregl.Map) {
    // AOI Boundary Layer
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
        "fill-opacity": 0.05,
      },
    });

    map.addLayer({
      id: "aoi-line",
      type: "line",
      source: "aoi-source",
      paint: {
        "line-color": "#06b6d4",
        "line-width": 2,
        "line-dasharray": [3, 2],
      },
    });

    // Population Zones
    map.addSource("population-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: "population-fill",
      type: "fill",
      source: "population-source",
      paint: {
        "fill-color": "#6366f1",
        "fill-opacity": 0.15,
      },
    });

    map.addLayer({
      id: "population-line",
      type: "line",
      source: "population-source",
      paint: {
        "line-color": "#6366f1",
        "line-width": 1.5,
        "line-dasharray": [2, 2],
      },
    });

    // Change Polygons Layer
    map.addSource("changes-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: "changes-fill",
      type: "fill",
      source: "changes-source",
      paint: {
        "fill-color": "#f43f5e",
        "fill-opacity": 0.45,
      },
    });

    map.addLayer({
      id: "changes-line",
      type: "line",
      source: "changes-source",
      paint: {
        "line-color": "#fda4af",
        "line-width": 1.5,
      },
    });

    // Infrastructure Layer
    map.addSource("infra-source", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: "infra-line",
      type: "line",
      source: "infra-source",
      filter: ["==", "$type", "LineString"],
      paint: {
        "line-color": "#38bdf8",
        "line-width": 3,
      },
    });

    map.addLayer({
      id: "infra-point",
      type: "circle",
      source: "infra-source",
      filter: ["==", "$type", "Point"],
      paint: {
        "circle-radius": 7,
        "circle-color": "#38bdf8",
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });

    // Click inspection
    map.on("click", "changes-fill", (e) => {
      if (!e.features || !e.features[0]) return;
      const feat = e.features[0];
      setSelectedFeatureInfo({
        category: "Change Polygon",
        ...feat.properties,
      });
    });

    map.on("click", "infra-point", (e) => {
      if (!e.features || !e.features[0]) return;
      const feat = e.features[0];
      setSelectedFeatureInfo({
        category: "Infrastructure Asset",
        ...feat.properties,
      });
    });

    map.on("mouseenter", "changes-fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "changes-fill", () => (map.getCanvas().style.cursor = ""));
    map.on("mouseenter", "infra-point", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "infra-point", () => (map.getCanvas().style.cursor = ""));
  }

  function updateMapData() {
    if (!mapRef.current) return;
    const map = mapRef.current;

    // 1. Update AOI Boundary
    const aoiSource = map.getSource("aoi-source") as maplibregl.GeoJSONSource;
    if (aoiSource) {
      if (selectedAoi && selectedAoi.geometry) {
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

    // 2. Update Change Polygons
    const changeSource = map.getSource("changes-source") as maplibregl.GeoJSONSource;
    if (changeSource) {
      if (changePolygons && changePolygons.features) {
        changeSource.setData(changePolygons);
      } else {
        changeSource.setData({ type: "FeatureCollection", features: [] });
      }
    }

    // 3. Update Infrastructure
    const infraSource = map.getSource("infra-source") as maplibregl.GeoJSONSource;
    if (infraSource) {
      if (allInfra && allInfra.features) {
        infraSource.setData(allInfra);
      } else {
        infraSource.setData({ type: "FeatureCollection", features: [] });
      }
    }
  }

  const promptPresets = [
    {
      title: "Mau Forest 2020-2025: Disturbance & Infrastructure",
      query: "Analyze vegetation change in Eastern Mau Forest between 2020 and 2025 and find nearby infrastructure within 1000m",
    },
    {
      title: "Harz National Park 2019-2024: Bark Beetle Dieback",
      query: "Analyze vegetation change in Harz National Park from 2019 to 2024 and evaluate proximity to infrastructure",
    },
    {
      title: "Cloudy Imagery Rejection Test",
      query: "Analyze Mau Forest with high cloud cover scene from 2024 and verify quality gate rejection",
    },
    {
      title: "Stable Canopy Baseline Check",
      query: "Analyze Mau Forest stable canopy baseline comparison from 2020",
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100vw", backgroundColor: "var(--bg-base)" }}>
      {/* Top Navigation Bar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 24px",
          backgroundColor: "var(--bg-surface)",
          borderBottom: "1px solid var(--border-color)",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "36px",
              height: "36px",
              borderRadius: "8px",
              background: "linear-gradient(135deg, #06b6d4, #10b981)",
              color: "#0f172a",
              fontWeight: 800,
            }}
          >
            <Compass size={22} />
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "16px", fontWeight: 800, letterSpacing: "-0.5px" }}>TERRALENS</span>
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  padding: "2px 6px",
                  borderRadius: "4px",
                  backgroundColor: "rgba(6, 182, 212, 0.15)",
                  color: "var(--accent-cyan)",
                  border: "1px solid rgba(6, 182, 212, 0.3)",
                }}
              >
                AI SPATIAL AGENT
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              Deterministic GIS Engine & PostGIS Spatial Intelligence
            </div>
          </div>
        </div>

        {/* System Health & Status Indicators */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px", fontSize: "12px" }}>
          {agentHealth && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <Bot size={14} color="var(--accent-emerald)" />
              <span style={{ color: "var(--text-secondary)" }}>
                Mode: <strong style={{ color: "var(--text-primary)" }}>{agentHealth.is_demo_mode ? "Deterministic Demo" : agentHealth.configured_llm_provider.toUpperCase()}</strong>
              </span>
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <Database size={14} color={health?.database.connected ? "var(--accent-emerald)" : "var(--accent-rose)"} />
            <span style={{ color: "var(--text-secondary)" }}>
              PostGIS: <strong style={{ color: health?.database.connected ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
                {health?.database.connected ? "Connected (3.x)" : "Offline"}
              </strong>
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <Satellite size={14} color="var(--accent-cyan)" />
            <span style={{ color: "var(--text-secondary)" }}>
              Scenes: <strong style={{ color: "var(--text-primary)" }}>{health?.database.counts.satellite_scenes || 0}</strong>
            </span>
          </div>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", position: "relative" }}>
        {/* Left Control & Agent Intelligence Sidebar */}
        <aside
          style={{
            width: "480px",
            minWidth: "480px",
            backgroundColor: "var(--bg-surface)",
            borderRight: "1px solid var(--border-color)",
            display: "flex",
            flexDirection: "column",
            zIndex: 5,
            boxShadow: "2px 0 12px rgba(0,0,0,0.3)",
          }}
        >
          {/* Navigation Tabs */}
          <div
            style={{
              display: "flex",
              borderBottom: "1px solid var(--border-color)",
              backgroundColor: "var(--bg-base)",
              padding: "4px 8px 0 8px",
              gap: "4px",
            }}
          >
            <button
              onClick={() => setActiveTab("agent")}
              style={{
                flex: 1.2,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                padding: "10px 4px",
                fontSize: "12px",
                fontWeight: 700,
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                backgroundColor: activeTab === "agent" ? "var(--bg-surface)" : "transparent",
                color: activeTab === "agent" ? "var(--accent-cyan)" : "var(--text-muted)",
                borderBottom: activeTab === "agent" ? "2px solid var(--accent-cyan)" : "none",
              }}
            >
              <Sparkles size={14} />
              AI Agent
            </button>

            <button
              onClick={() => setActiveTab("analysis")}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                padding: "10px 4px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                backgroundColor: activeTab === "analysis" ? "var(--bg-surface)" : "transparent",
                color: activeTab === "analysis" ? "var(--accent-cyan)" : "var(--text-muted)",
                borderBottom: activeTab === "analysis" ? "2px solid var(--accent-cyan)" : "none",
              }}
            >
              <Activity size={14} />
              NDVI GIS
            </button>

            <button
              onClick={() => setActiveTab("spatial")}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                padding: "10px 4px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                backgroundColor: activeTab === "spatial" ? "var(--bg-surface)" : "transparent",
                color: activeTab === "spatial" ? "var(--accent-cyan)" : "var(--text-muted)",
                borderBottom: activeTab === "spatial" ? "2px solid var(--accent-cyan)" : "none",
              }}
            >
              <MapPin size={14} />
              Spatial
            </button>

            <button
              onClick={() => setActiveTab("population")}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                padding: "10px 4px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                backgroundColor: activeTab === "population" ? "var(--bg-surface)" : "transparent",
                color: activeTab === "population" ? "var(--accent-cyan)" : "var(--text-muted)",
                borderBottom: activeTab === "population" ? "2px solid var(--accent-cyan)" : "none",
              }}
            >
              <Users size={14} />
              Demography
            </button>

            <button
              onClick={() => setActiveTab("scenes")}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                padding: "10px 4px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                backgroundColor: activeTab === "scenes" ? "var(--bg-surface)" : "transparent",
                color: activeTab === "scenes" ? "var(--accent-cyan)" : "var(--text-muted)",
                borderBottom: activeTab === "scenes" ? "2px solid var(--accent-cyan)" : "none",
              }}
            >
              <Layers size={14} />
              Catalog
            </button>
          </div>

          {/* Sidebar Content Container */}
          <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* Status Notification Banner */}
            {statusMessage && (
              <div
                style={{
                  padding: "10px 12px",
                  borderRadius: "6px",
                  backgroundColor: "rgba(6, 182, 212, 0.1)",
                  border: "1px solid rgba(6, 182, 212, 0.3)",
                  fontSize: "12px",
                  color: "var(--accent-cyan)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span>{statusMessage}</span>
                <button
                  onClick={() => setStatusMessage(null)}
                  style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "14px" }}
                >
                  ✕
                </button>
              </div>
            )}

            {/* TAB 1: AI Agent Analysis Panel (Phase 4 Primary) */}
            {activeTab === "agent" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", fontWeight: 700, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: "6px" }}>
                    <Bot size={14} color="var(--accent-cyan)" />
                    Natural Language Geospatial Inquiry
                  </label>
                  <textarea
                    rows={3}
                    value={agentQuery}
                    onChange={(e) => setAgentQuery(e.target.value)}
                    placeholder="E.g. Analyze vegetation change in Eastern Mau Forest between 2020 and 2025..."
                    style={{
                      width: "100%",
                      padding: "10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-base)",
                      border: "1px solid var(--border-color)",
                      color: "var(--text-primary)",
                      fontSize: "12px",
                      resize: "none",
                      fontFamily: "inherit",
                    }}
                  />
                </div>

                {/* Preset Suggestion Chips */}
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <span style={{ fontSize: "11px", color: "var(--text-muted)", fontWeight: 600 }}>Suggested Inquiries:</span>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    {promptPresets.map((preset, idx) => (
                      <button
                        key={idx}
                        onClick={() => setAgentQuery(preset.query)}
                        style={{
                          textAlign: "left",
                          padding: "6px 10px",
                          borderRadius: "4px",
                          backgroundColor: "var(--bg-surface)",
                          border: "1px solid var(--border-color)",
                          color: "var(--text-secondary)",
                          fontSize: "11px",
                          cursor: "pointer",
                          transition: "all 0.15s ease",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent-cyan)")}
                        onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border-color)")}
                      >
                        {preset.title}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Execute Button */}
                <button
                  onClick={handleExecuteAgent}
                  disabled={isAgentExecuting || !agentQuery.trim()}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    padding: "12px",
                    borderRadius: "6px",
                    backgroundColor: isAgentExecuting ? "var(--bg-surface)" : "var(--accent-cyan)",
                    color: isAgentExecuting ? "var(--text-muted)" : "#0f172a",
                    fontWeight: 700,
                    fontSize: "13px",
                    border: "none",
                    cursor: isAgentExecuting ? "not-allowed" : "pointer",
                    boxShadow: isAgentExecuting ? "none" : "0 4px 14px rgba(6, 182, 212, 0.3)",
                  }}
                >
                  {isAgentExecuting ? (
                    <>
                      <Activity size={16} className="animate-spin" />
                      Orchestrating Tool Pipeline...
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} />
                      Execute AI Agent Analysis
                    </>
                  )}
                </button>

                {/* Agent Structured Response Section */}
                {agentResponse && (
                  <div
                    style={{
                      marginTop: "8px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "12px",
                      padding: "14px",
                      borderRadius: "8px",
                      backgroundColor: "var(--bg-base)",
                      border: "1px solid var(--border-color)",
                    }}
                  >
                    {/* Header: Status & Recommended Action */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: 800,
                          textTransform: "uppercase",
                          padding: "3px 8px",
                          borderRadius: "4px",
                          backgroundColor:
                            agentResponse.status === "validated"
                              ? "rgba(16, 185, 129, 0.2)"
                              : agentResponse.status === "not_actionable"
                              ? "rgba(148, 163, 184, 0.2)"
                              : "rgba(244, 63, 94, 0.2)",
                          color:
                            agentResponse.status === "validated"
                              ? "var(--accent-emerald)"
                              : agentResponse.status === "not_actionable"
                              ? "var(--text-muted)"
                              : "var(--accent-rose)",
                          border: `1px solid ${
                            agentResponse.status === "validated"
                              ? "var(--accent-emerald)"
                              : agentResponse.status === "not_actionable"
                              ? "var(--text-muted)"
                              : "var(--accent-rose)"
                          }`,
                        }}
                      >
                        STATUS: {agentResponse.status.toUpperCase()}
                      </span>

                      <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                        Mode: {agentResponse.orchestration_mode}
                      </span>
                    </div>

                    {/* Recommended Action Badge */}
                    <div
                      style={{
                        padding: "8px 10px",
                        borderRadius: "6px",
                        backgroundColor: "var(--bg-surface)",
                        border: "1px solid var(--border-color)",
                        fontSize: "12px",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                      }}
                    >
                      {agentResponse.recommended_action === "ISSUE_MONITORING_ALERT" ? (
                        <AlertTriangle size={16} color="var(--accent-amber)" />
                      ) : agentResponse.recommended_action === "NO_ACTION_REQUIRED" ? (
                        <CheckCircle2 size={16} color="var(--accent-emerald)" />
                      ) : (
                        <XCircle size={16} color="var(--accent-rose)" />
                      )}
                      <div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase" }}>
                          Recommended Action
                        </div>
                        <div style={{ fontWeight: 700, color: "var(--text-primary)" }}>
                          {agentResponse.recommended_action}
                        </div>
                      </div>
                    </div>

                    {/* Quantitative Change & Impact Metrics Grid */}
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "8px",
                        fontSize: "11px",
                      }}
                    >
                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-surface)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Change Area</div>
                        <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--accent-rose)" }}>
                          {agentResponse.change.area_ha.toFixed(2)} ha
                        </div>
                      </div>

                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-surface)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Polygons</div>
                        <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--text-primary)" }}>
                          {agentResponse.change.polygon_count}
                        </div>
                      </div>

                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-surface)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Nearby Assets</div>
                        <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--accent-cyan)" }}>
                          {agentResponse.spatial_impact.infrastructure_count} within {radiusM}m
                        </div>
                      </div>

                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-surface)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Intersecting Population</div>
                        <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--accent-indigo)" }}>
                          {(agentResponse.spatial_impact.population_context.total_intersecting_population || 0).toLocaleString()}
                        </div>
                      </div>
                    </div>

                    {/* Quality Gate Checks Breakdown */}
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                      <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: "4px" }}>
                        <ShieldCheck size={14} color="var(--accent-emerald)" />
                        Deterministic Quality Gate: {agentResponse.validation.passed ? "PASSED" : "FAILED"}
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        {agentResponse.validation.checks.map((check, idx) => (
                          <div
                            key={idx}
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
                              gap: "6px",
                              fontSize: "10px",
                              color: check.status === "PASSED" ? "var(--text-secondary)" : "var(--accent-rose)",
                            }}
                          >
                            {check.status === "PASSED" ? (
                              <CheckCircle2 size={12} color="var(--accent-emerald)" style={{ marginTop: "1px", flexShrink: 0 }} />
                            ) : (
                              <XCircle size={12} color="var(--accent-rose)" style={{ marginTop: "1px", flexShrink: 0 }} />
                            )}
                            <span>{check.description}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Evidence List */}
                    {agentResponse.evidence.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-primary)" }}>
                          Factual Evidence:
                        </div>
                        <ul style={{ margin: 0, paddingLeft: "16px", fontSize: "11px", color: "var(--text-secondary)" }}>
                          {agentResponse.evidence.map((item, idx) => (
                            <li key={idx} style={{ marginBottom: "2px" }}>
                              {item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Reasoning Summary */}
                    {agentResponse.reasoning_summary && (
                      <div
                        style={{
                          padding: "8px 10px",
                          borderRadius: "4px",
                          backgroundColor: "rgba(255, 255, 255, 0.03)",
                          fontSize: "11px",
                          color: "var(--text-muted)",
                          lineHeight: 1.4,
                        }}
                      >
                        <strong>Synthesis:</strong> {agentResponse.reasoning_summary}
                      </div>
                    )}

                    {/* Activity Log Stepper */}
                    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                      <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: "4px" }}>
                        <Terminal size={12} />
                        Workflow Activity Log ({agentResponse.activity_log.length} steps)
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "3px", maxHeight: "120px", overflowY: "auto" }}>
                        {agentResponse.activity_log.map((log, idx) => (
                          <div
                            key={idx}
                            style={{
                              fontSize: "10px",
                              fontFamily: "var(--font-mono)",
                              color: log.status === "FAILED" ? "var(--accent-rose)" : "var(--text-muted)",
                            }}
                          >
                            [{log.step}] {log.tool ? `tool:${log.tool} - ` : ""}{log.summary}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: Deterministic NDVI GIS Panel */}
            {activeTab === "analysis" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                {/* AOI Selector */}
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", fontWeight: 700, color: "var(--text-primary)" }}>Area of Interest (AOI)</label>
                  <select
                    value={selectedAoi?.id || ""}
                    onChange={(e) => {
                      const a = aois.find((x) => x.id === e.target.value);
                      if (a) setSelectedAoi(a);
                    }}
                    style={{
                      padding: "8px 10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-base)",
                      border: "1px solid var(--border-color)",
                      color: "var(--text-primary)",
                      fontSize: "12px",
                    }}
                  >
                    {aois.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.area_hectares} ha)
                      </option>
                    ))}
                  </select>
                </div>

                {/* Scene Comparison Selectors */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", color: "var(--text-muted)" }}>Baseline Scene (Before)</label>
                    <select
                      value={beforeSceneId}
                      onChange={(e) => setBeforeSceneId(e.target.value)}
                      style={{
                        padding: "6px 8px",
                        borderRadius: "4px",
                        backgroundColor: "var(--bg-base)",
                        border: "1px solid var(--border-color)",
                        color: "var(--text-primary)",
                        fontSize: "11px",
                      }}
                    >
                      {scenes.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.acquisition_date} ({s.cloud_cover}% cloud)
                        </option>
                      ))}
                    </select>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", color: "var(--text-muted)" }}>Comparison Scene (After)</label>
                    <select
                      value={afterSceneId}
                      onChange={(e) => setAfterSceneId(e.target.value)}
                      style={{
                        padding: "6px 8px",
                        borderRadius: "4px",
                        backgroundColor: "var(--bg-base)",
                        border: "1px solid var(--border-color)",
                        color: "var(--text-primary)",
                        fontSize: "11px",
                      }}
                    >
                      {scenes.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.acquisition_date} ({s.cloud_cover}% cloud)
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Threshold Slider */}
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px" }}>
                    <span style={{ color: "var(--text-muted)" }}>NDVI Decrease Threshold (ΔNDVI):</span>
                    <span style={{ fontWeight: 700, color: "var(--accent-rose)" }}>{threshold.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min="-0.50"
                    max="-0.05"
                    step="0.05"
                    value={threshold}
                    onChange={(e) => setThreshold(parseFloat(e.target.value))}
                    style={{ width: "100%", accentColor: "var(--accent-rose)" }}
                  />
                </div>

                {/* Trigger Button */}
                <button
                  onClick={handleRunNDVI}
                  disabled={isAnalyzing || !selectedAoi || !beforeSceneId || !afterSceneId}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    padding: "10px",
                    borderRadius: "6px",
                    backgroundColor: "var(--accent-rose)",
                    color: "#ffffff",
                    fontWeight: 700,
                    fontSize: "12px",
                    border: "none",
                    cursor: isAnalyzing ? "not-allowed" : "pointer",
                  }}
                >
                  <Play size={14} />
                  {isAnalyzing ? "Processing Raster Algebra..." : "Run NDVI Change Analysis"}
                </button>

                {/* Past Analysis Runs */}
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "6px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-primary)" }}>Recent Analysis Runs</span>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    {analysisRuns.slice(0, 4).map((run) => (
                      <div
                        key={run.id}
                        onClick={async () => {
                          setActiveAnalysisId(run.id);
                          const changes = await fetchAnalysisChanges(run.id);
                          setChangePolygons(changes);
                        }}
                        style={{
                          padding: "8px 10px",
                          borderRadius: "4px",
                          backgroundColor: activeAnalysisId === run.id ? "rgba(6, 182, 212, 0.15)" : "var(--bg-base)",
                          border: `1px solid ${activeAnalysisId === run.id ? "var(--accent-cyan)" : "var(--border-color)"}`,
                          cursor: "pointer",
                          fontSize: "11px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                          <span style={{ fontWeight: 600 }}>{run.aoi_name}</span>
                          <span style={{ color: "var(--accent-rose)", fontWeight: 700 }}>{run.total_change_area_ha.toFixed(2)} ha</span>
                        </div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                          {run.change_polygon_count} polygons | Threshold: {run.threshold}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* TAB 3: Phase 3 PostGIS Spatial Intelligence */}
            {activeTab === "spatial" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                    <span style={{ color: "var(--text-muted)" }}>Proximity Search Radius:</span>
                    <strong style={{ color: "var(--accent-cyan)" }}>{radiusM} meters</strong>
                  </div>
                  <input
                    type="range"
                    min="200"
                    max="5000"
                    step="100"
                    value={radiusM}
                    onChange={(e) => setRadiusM(parseInt(e.target.value))}
                    style={{ width: "100%", accentColor: "var(--accent-cyan)" }}
                  />
                </div>

                {nearbyInfra && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "11px" }}>
                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-base)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Assets within {radiusM}m</div>
                        <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--accent-cyan)" }}>
                          {nearbyInfra.infrastructure_count}
                        </div>
                      </div>
                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-base)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Associated Change</div>
                        <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--accent-rose)" }}>
                          {nearbyInfra.associated_change_area_ha.toFixed(2)} ha
                        </div>
                      </div>
                    </div>

                    <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-primary)", marginTop: "4px" }}>
                      Nearby Assets (ST_DWithin PostGIS GIST):
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                      {nearbyInfra.infrastructure.map((item) => (
                        <div
                          key={item.id}
                          style={{
                            padding: "8px 10px",
                            borderRadius: "4px",
                            backgroundColor: "var(--bg-base)",
                            border: "1px solid var(--border-color)",
                            fontSize: "11px",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                            <span style={{ fontWeight: 600 }}>{item.name}</span>
                            <span style={{ color: item.distance_m === 0 ? "var(--accent-rose)" : "var(--accent-emerald)", fontWeight: 700 }}>
                              {item.distance_m === 0 ? "INTERSECTS (0m)" : `${item.distance_m.toFixed(0)}m`}
                            </span>
                          </div>
                          <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>Type: {item.type}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 4: Population Demographic Overlays */}
            {activeTab === "population" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {popContext && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "11px" }}>
                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-base)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Nearby Zones</div>
                        <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--accent-indigo)" }}>
                          {popContext.population_zones_count}
                        </div>
                      </div>
                      <div style={{ padding: "8px", borderRadius: "4px", backgroundColor: "var(--bg-base)" }}>
                        <div style={{ color: "var(--text-muted)" }}>Intersecting Population</div>
                        <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--accent-rose)" }}>
                          {popContext.total_intersecting_population.toLocaleString()}
                        </div>
                      </div>
                    </div>

                    <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-primary)", marginTop: "4px" }}>
                      Settlement Zones:
                    </div>

                    {popContext.zones.map((zone) => (
                      <div
                        key={zone.id}
                        style={{
                          padding: "8px 10px",
                          borderRadius: "4px",
                          backgroundColor: "var(--bg-base)",
                          border: "1px solid var(--border-color)",
                          fontSize: "11px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                          <span style={{ fontWeight: 600 }}>{zone.name}</span>
                          <span style={{ color: "var(--accent-indigo)", fontWeight: 700 }}>
                            Pop: {zone.population.toLocaleString()}
                          </span>
                        </div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                          {zone.intersects_change ? `Directly Intersects Change Polygons (${zone.intersection_area_ha.toFixed(2)} ha)` : `Distance: ${zone.distance_m.toFixed(0)}m`}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* TAB 5: Scene Catalog */}
            {activeTab === "scenes" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {scenes.map((scene) => (
                  <div
                    key={scene.id}
                    style={{
                      padding: "10px",
                      borderRadius: "6px",
                      backgroundColor: "var(--bg-base)",
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

        {/* Right Main Map Visualization */}
        <main style={{ position: "relative", flex: 1, height: "100%" }}>
          <div ref={mapContainer} style={{ width: "100%", height: "100%" }} />

          {/* Map Layer Legend */}
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
              <span>Infrastructure Assets (PostGIS GIST)</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "12px", height: "12px", borderRadius: "2px", backgroundColor: "rgba(99, 102, 241, 0.2)", border: "1px dashed #6366f1" }} />
              <span>Population Settlement Zones</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "14px", height: "0px", borderTop: "2px dashed #06b6d4" }} />
              <span>Official AOI Boundary (EPSG:4326)</span>
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
                    Distance: <strong>{selectedFeatureInfo.distance_m === 0 ? "0 m (Intersects)" : `${Number(selectedFeatureInfo.distance_m || 0).toFixed(1)} m`}</strong>
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
