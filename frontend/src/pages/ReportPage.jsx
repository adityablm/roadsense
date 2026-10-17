import { useEffect, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import { markNotDamage, sendReport } from "../api.js";
import DetectionImage from "../components/DetectionImage.jsx";
import SeverityScale from "../components/SeverityScale.jsx";
import { HOME, SOURCE_TEXT as DECIDED_BY, USER_CHOICES, damageName, formatCoord } from "../labels.js";

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
  const [missedLabel, setMissedLabel] = useState(null);   // what the person says the AI missed
  const [missedNote, setMissedNote] = useState("");

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

  // Sends the photo. `extra` is used for the second try: confirming "possible" damage,
  // or reporting damage the AI missed.
  async function send(extra = {}) {
    if (!file) return;
    setSending(true);
    setError(null);
    try {
      setResult(await sendReport({ file, lat: place?.lat, lng: place?.lng, ...extra }));
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    setResult(null);
    setMissedLabel(null);
    setMissedNote("");
    send();
  }

  function reportMissed(e) {
    e.preventDefault();
    send({ userLabel: missedLabel, userNote: missedNote.trim() });
  }

  const noteNeeded = missedLabel === "other" && missedNote.trim().length < 3;

  async function notDamage() {
    setSending(true);
    setError(null);
    try {
      await markNotDamage(result.report_id);
      setResult({ ...result, removed: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  function reset() {
    setMissedLabel(null);
    setMissedNote("");
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
          {error && <p className="error" role="alert">{error}</p>}
          <h2>
            {result.removed ? "Removed from the map" : result.damage_found
              ? (result.source === "model" ? "Damage found" : "Damage reported")
              : result.possible_detections.length > 0 ? "Possible damage" : "No damage found"}
          </h2>
          <DetectionImage
            src={preview}
            detections={result.damage_found ? result.detections : result.possible_detections}
            possible={!result.damage_found}
            alt="Your photo with the damage marked"
          />
          {result.removed ? (
            <>
              <p>
                Thanks. This photo is off the map and out of the numbers. It's kept privately as an example of
                a mistake, so the AI can be retrained to avoid it.
              </p>
              <div className="result-actions">
                <button className="btn btn-primary" onClick={reset}>Report another photo</button>
              </div>
            </>
          ) : result.damage_found ? (
            <>
              <SeverityScale score={result.severity} level={result.level} size="large" />
              <ul className="found-list">
                {result.detections.map((d, i) => (
                  <li key={i}>
                    {damageName(d.label)}
                    {d.confidence != null ? `, ${Math.round(d.confidence * 100)}% sure` : ""}
                    {d.note ? `: "${d.note}"` : ""}
                  </li>
                ))}
              </ul>
              {result.source !== "model" && (
                <p className="unverified-flag">
                  {DECIDED_BY[result.source]}. It shows on the map with a dashed outline until the AI or other
                  people confirm it.
                </p>
              )}
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
              {result.source === "model" && (
                <p className="wrong-line">
                  Is the AI wrong?{" "}
                  <button className="link-btn" disabled={sending} onClick={notDamage}>
                    {sending ? "Removing…" : "This isn't damage, remove it"}
                  </button>
                </p>
              )}
            </>
          ) : result.possible_detections.length > 0 ? (
            <>
              <p>
                The AI isn't sure. It thinks there may be damage where the dashed box is. Is it really there?
              </p>
              <div className="result-actions">
                <button className="btn btn-primary" disabled={sending} onClick={() => send({ acceptPossible: true })}>
                  {sending ? "Saving…" : "Yes, report it"}
                </button>
                <button className="btn btn-ghost" disabled={sending}
                        onClick={() => setResult({ ...result, possible_detections: [] })}>
                  No, the boxes are wrong
                </button>
              </div>
            </>
          ) : (
            <>
              <p>
                The AI didn't find potholes or cracks in this photo. If the damage is really there,
                tell us what it is and it will still go on the map, marked as not confirmed by the AI.
              </p>
              <form className="missed" onSubmit={reportMissed}>
                <fieldset>
                  <legend>What did the AI miss?</legend>
                  <div className="choices">
                    {USER_CHOICES.map((label) => (
                      <label key={label} className="choice">
                        <input type="radio" name="missed" value={label} checked={missedLabel === label}
                               onChange={() => setMissedLabel(label)} />
                        <span>{damageName(label)}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                {missedLabel === "other" && (
                  <label className="missed-note">
                    Describe it in a few words
                    <input type="text" maxLength={80} value={missedNote} placeholder="e.g. sunken manhole cover"
                           onChange={(e) => setMissedNote(e.target.value)} />
                  </label>
                )}
                <div className="result-actions">
                  <button type="submit" className="btn btn-primary" disabled={!missedLabel || noteNeeded || sending}>
                    {sending ? "Saving…" : "Report it myself"}
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={reset}>Try another photo</button>
                </div>
              </form>
            </>
          )}
        </section>
      )}
    </div>
  );
}
