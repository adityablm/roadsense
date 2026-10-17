import { useCallback, useEffect, useRef, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import { getHotspots } from "../api.js";
import { HOME, LEVELS, damageName } from "../labels.js";
import HotspotPanel from "./HotspotPanel.jsx";

// Bigger circle = more reports. Square root so 100 reports isn't 100x bigger than 1.
const radiusFor = (reports) => Math.min(24, 7 + 3 * Math.sqrt(reports));

// Asks the server for hotspots every time the visible map area changes.
function ViewportLoader({ onLoad, onError }) {
  const map = useMap();
  const load = useCallback(() => {
    const b = map.getBounds();
    getHotspots({
      min_lat: b.getSouth(), min_lng: b.getWest(),
      max_lat: b.getNorth(), max_lng: b.getEast(),
    }).then(onLoad, onError);
  }, [map, onLoad, onError]);
  useMapEvents({ moveend: load });
  useEffect(load, [load]);
  return null;
}

// Moves the map to a hotspot when it is opened from a link (e.g. after reporting).
function FlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo([target.lat, target.lng], Math.max(map.getZoom(), 16), { duration: 0.8 });
  }, [map, target]);
  return null;
}

export default function MapPage({ selectedId, onSelect, onNavigate }) {
  const [hotspots, setHotspots] = useState(null);
  const [error, setError] = useState(null);
  const [flyTarget, setFlyTarget] = useState(null);
  const firstLoad = useRef(true);

  const handleLoad = useCallback((rows) => {
    setHotspots(rows);
    setError(null);
  }, []);
  const handleError = useCallback((e) => setError(e.message), []);

  // When a hotspot was chosen by link, fly there once its position is known.
  const handleDetail = useCallback((detail) => {
    if (firstLoad.current) {
      setFlyTarget({ lat: detail.lat, lng: detail.lng });
      firstLoad.current = false;
    }
  }, []);

  return (
    <div className="map-page">
      <MapContainer center={[HOME.lat, HOME.lng]} zoom={HOME.zoom} className="map" zoomControl={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ZoomControl position="bottomright" />
        <ViewportLoader onLoad={handleLoad} onError={handleError} />
        <FlyTo target={flyTarget} />
        {(hotspots || []).map((h) => {
          const color = LEVELS[h.level].color;
          const selected = h.id === selectedId;
          return (
            <CircleMarker
              key={h.id}
              center={[h.lat, h.lng]}
              radius={radiusFor(h.report_count)}
              pathOptions={h.verified ? {
                color: selected ? "#23262a" : "#ffffff",
                weight: selected ? 4 : 2,
                fillColor: color,
                fillOpacity: 0.85,
              } : {
                // reported by people but not confirmed by the AI: dashed outline, light fill
                color: selected ? "#23262a" : color,
                weight: selected ? 4 : 3,
                dashArray: "5 4",
                fillColor: color,
                fillOpacity: 0.2,
              }}
              eventHandlers={{ click: () => onSelect(h.id) }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                {LEVELS[h.level].name}: {Object.keys(h.damage_counts).map(damageName).join(", ")}
                <br />
                {h.report_count} {h.report_count === 1 ? "report" : "reports"}
                {!h.verified && <><br />Not confirmed by the AI</>}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <aside className="legend" aria-label="Map key">
        {["severe", "moderate", "minor"].map((level) => (
          <span key={level}>
            <i style={{ background: LEVELS[level].color }} /> {LEVELS[level].name}
          </span>
        ))}
        <small>Bigger circle, more reports</small>
        <small>Dashed outline: reported by people, not confirmed by the AI</small>
      </aside>

      {error && (
        <div className="map-message map-error" role="alert">
          {error}
        </div>
      )}
      {!error && hotspots && hotspots.length === 0 && !selectedId && (
        <div className="map-message">
          <p>No damage reported in this part of the map yet.</p>
          <button className="btn btn-primary" onClick={() => onNavigate("report")}>
            Report a damaged road
          </button>
        </div>
      )}

      {selectedId && (
        <HotspotPanel id={selectedId} onClose={() => onSelect(null)} onLoaded={handleDetail} />
      )}
    </div>
  );
}
