import { useEffect, useState } from "react";
import { draftLetter, getHotspot, imageUrl } from "../api.js";
import DetectionImage from "../components/DetectionImage.jsx";
import SeverityScale from "../components/SeverityScale.jsx";
import { SOURCE_TEXT, damageName, formatCoord, formatDate } from "../labels.js";

const STATUS = {
  open: "Open",
  complaint_drafted: "Complaint letter drafted",
  fixed: "Fixed",
};

export default function HotspotPanel({ id, onClose, onLoaded }) {
  const [spot, setSpot] = useState(null);
  const [error, setError] = useState(null);
  const [letter, setLetter] = useState(null);       // { lang, text }
  const [writing, setWriting] = useState(null);     // which language is being written
  const [letterError, setLetterError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSpot(null);
    setError(null);
    setLetter(null);
    setLetterError(null);
    getHotspot(id).then(
      (data) => {
        if (cancelled) return;
        setSpot(data);
        onLoaded?.(data);
      },
      (e) => !cancelled && setError(e.message),
    );
    return () => {
      cancelled = true;
    };
  }, [id, onLoaded]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function write(lang, refresh = false) {
    setWriting(lang);
    setLetterError(null);
    setCopied(false);
    try {
      const result = await draftLetter(id, lang, refresh);
      setLetter({ lang, text: result.letter });
      setSpot((s) => s && { ...s, status: s.status === "open" ? "complaint_drafted" : s.status });
    } catch (e) {
      setLetterError(e.message);
    } finally {
      setWriting(null);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(letter.text);
      setCopied(true);
    } catch {
      setLetterError("Couldn't copy automatically. Select the letter text and copy it yourself.");
    }
  }

  return (
    <aside className="panel" aria-label="Damaged spot details">
      <div className="panel-head">
        <h2>Spot {id}</h2>
        <button className="btn btn-ghost" onClick={onClose} aria-label="Close details">
          Close
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!spot && !error && <p className="muted">Loading this spot…</p>}

      {spot && (
        <div className="panel-body">
          {spot.is_demo && <p className="demo-flag">Sample data, added to show how the app works.</p>}
          <SeverityScale score={spot.severity} level={spot.level} size="large" />
          {!spot.verified && (
            <p className="unverified-flag">
              Not confirmed by the AI yet. People reported this damage, but the AI didn't spot it confidently.
            </p>
          )}

          <dl className="facts">
            <dt>Where</dt>
            <dd>
              {spot.address || "Address not looked up yet"}
              <br />
              <a href={`https://www.openstreetmap.org/?mlat=${spot.lat}&mlon=${spot.lng}#map=19/${spot.lat}/${spot.lng}`}
                 target="_blank" rel="noreferrer">
                {formatCoord(spot.lat, spot.lng)}
              </a>
            </dd>
            <dt>Damage seen</dt>
            <dd>
              {Object.entries(spot.damage_counts)
                .map(([label, n]) => `${damageName(label)} × ${n}`)
                .join(", ")}
            </dd>
            <dt>Reported by</dt>
            <dd>
              {spot.reporter_count} {spot.reporter_count === 1 ? "person" : "people"}, in {spot.report_count}{" "}
              {spot.report_count === 1 ? "photo" : "photos"}
              {spot.reporter_count === 1 && (
                <span className="muted"> (a second person must report it before it can count as severe)</span>
              )}
            </dd>
            <dt>First seen</dt>
            <dd>{formatDate(spot.first_reported)}</dd>
            <dt>Last seen</dt>
            <dd>{formatDate(spot.last_reported)}</dd>
            <dt>Status</dt>
            <dd>{STATUS[spot.status] || spot.status}</dd>
          </dl>

          <section className="letter">
            <h3>Complaint letter</h3>
            <p className="muted">
              Written by AI using only the facts above. Check it, add your name, and send it to the municipal office.
            </p>
            <div className="letter-buttons">
              <button className="btn btn-primary" disabled={!!writing} onClick={() => write("en")}>
                {writing === "en" ? "Writing…" : "Write in English"}
              </button>
              <button className="btn btn-primary" disabled={!!writing} onClick={() => write("te")} lang="te">
                {writing === "te" ? "రాస్తోంది…" : "తెలుగులో రాయండి"}
              </button>
            </div>
            {writing && <p className="muted">Usually takes 5–20 seconds. If the AI is busy, RoadSense tries other models, which can take up to a minute.</p>}
            {letterError && <p className="error">{letterError}</p>}
            {letter && (
              <div className="letter-out">
                <pre lang={letter.lang}>{letter.text}</pre>
                <div className="letter-buttons">
                  <button className="btn btn-ghost" onClick={copy}>
                    {copied ? "Copied" : "Copy letter"}
                  </button>
                  <button className="btn btn-ghost" disabled={!!writing} onClick={() => write(letter.lang, true)}>
                    {writing ? "Writing…" : "Write a new version"}
                  </button>
                </div>
              </div>
            )}
          </section>

          <section>
            <h3>Photos</h3>
            <div className="photos">
              {spot.reports.map((r) => (
                <div key={r.id} className="photo">
                  <DetectionImage
                    src={imageUrl(r.image_url)}
                    detections={r.detections}
                    alt={`Road photo from ${formatDate(r.created_at)}`}
                  />
                  <p className="muted">
                    {formatDate(r.created_at)}, severity {r.severity.toFixed(1)}
                    {SOURCE_TEXT[r.source] && <><br />{SOURCE_TEXT[r.source]}</>}
                    {r.detections.filter((d) => d.note).map((d, i) => (
                      <span key={i}><br />"{d.note}"</span>
                    ))}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </aside>
  );
}
