import { useEffect, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import { sendReport } from "../api.js";
import DetectionImage from "../components/DetectionImage.jsx";
import SeverityScale from "../components/SeverityScale.jsx";
import { HOME, damageName, formatCoord } from "../labels.js";

// Lets the person click on the small map to say where the photo was taken.
function ClickToPin({ onPin }) {
  useMapEvents({ click: (e) => onPin({ lat: e.latlng.lat, lng: e.latlng.lng, source: "map" }) });
  return null;
}

const SOURCE_TEXT = {
  device: "your current location",
  map: "the spot you pinned on the map",
};

export default function ReportPage({ onNavigate }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [place, setPlace] = useState(null);        // { lat, lng, source }
  const [locating, setLocating] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!file) return undefined;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function choosePhoto(e) {
    const chosen = e.target.files?.[0];
    if (!chosen) return;
    setFile(chosen);
    setResult(null);
    setError(null);
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setError("This browser can't share its location. Pin the spot on the map instead.");
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPlace({ lat: pos.coords.latitude, lng: pos.coords.longitude, source: "device" });
        setLocating(false);
      },
      () => {
        setError("Location was blocked or unavailable. Pin the spot on the map instead.");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }

  async function submit(e) {
    e.preventDefault();
    if (!file) return;
    setSending(true);
    setError(null);
    setResult(null);
    try {
      setResult(await sendReport({ file, lat: place?.lat, lng: place?.lng }));
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setPlace(null);
    setResult(null);
    setError(null);
  }

  return (
    <div className="page report-page">
      <header className="page-intro">
        <h1>Report a damaged road</h1>
        <p>
          Take or choose a photo of the road. RoadSense looks for potholes and cracks, and adds the spot to the map.
          If other people already reported the same spot, your photo is added to theirs.
        </p>
      </header>

      <form className="report-steps" onSubmit={submit}>
        <section className="step">
          <h2><span className="step-n">1</span> Photo</h2>
          <label className="drop">
            <input type="file" accept="image/jpeg,image/png,image/webp" onChange={choosePhoto} />
            {preview ? (
              <img src={preview} alt="The photo you chose" />
            ) : (
              <span>{file ? "Choose a different photo" : "Choose a photo of the road"}</span>
            )}
          </label>
          {file && <p className="muted">{file.name}</p>}
        </section>

        <section className="step">
          <h2><span className="step-n">2</span> Where was it taken?</h2>
          <button type="button" className="btn btn-ghost" onClick={useMyLocation} disabled={locating}>
            {locating ? "Finding you…" : "Use my current location"}
          </button>
          <p className="muted">Or click the map to pin the exact spot.</p>
          <div className="mini-map">
            <MapContainer center={[HOME.lat, HOME.lng]} zoom={HOME.zoom} className="map">
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <ClickToPin onPin={setPlace} />
              {place && (
                <CircleMarker
                  center={[place.lat, place.lng]}
                  radius={9}
                  pathOptions={{ color: "#23262a", weight: 3, fillColor: "#f2c400", fillOpacity: 1 }}
                />
              )}
            </MapContainer>
          </div>
          <p className="location-line">
            {place
              ? <>Using {SOURCE_TEXT[place.source]}: {formatCoord(place.lat, place.lng)}</>
              : "If you skip this, the location saved inside the photo is used (most phone cameras save it)."}
          </p>
        </section>

        <section className="step step-send">
          <h2><span className="step-n">3</span> Check the photo</h2>
          <button type="submit" className="btn btn-primary btn-big" disabled={!file || sending}>
            {sending ? "Looking for damage…" : "Check this photo"}
          </button>
          {error && <p className="error" role="alert">{error}</p>}
        </section>
      </form>

      {result && (
        <section className="result" aria-live="polite">
          <h2>{result.damage_found ? "Damage found" : "No damage found"}</h2>
          <DetectionImage src={preview} detections={result.detections} alt="Your photo with the damage marked" />
          {result.damage_found ? (
            <>
              <SeverityScale score={result.severity} level={result.level} size="large" />
              <ul className="found-list">
                {result.detections.map((d, i) => (
                  <li key={i}>
                    {damageName(d.label)}, {Math.round(d.confidence * 100)}% sure
                  </li>
                ))}
              </ul>
              <p>
                {result.merged_into_existing
                  ? "Someone already reported this spot. Your photo was added to it, which makes the report stronger."
                  : "This is a new spot on the map. If others report it too, it moves up the list."}
              </p>
              <div className="result-actions">
                <button className="btn btn-primary" onClick={() => onNavigate("map", result.hotspot_id)}>
                  See it on the map
                </button>
                <button className="btn btn-ghost" onClick={reset}>Report another photo</button>
              </div>
            </>
          ) : (
            <>
              <p>
                The model didn't find potholes or cracks in this photo, so nothing was saved.
                Try a closer photo of the road surface, taken in daylight.
              </p>
              <button className="btn btn-ghost" onClick={reset}>Try another photo</button>
            </>
          )}
        </section>
      )}
    </div>
  );
}
