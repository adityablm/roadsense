import { useEffect, useState } from "react";
import { getStats } from "../api.js";
import SeverityScale from "../components/SeverityScale.jsx";
import { DAMAGE, LEVELS, damageName, formatCoord } from "../labels.js";

export default function StatsPage({ onNavigate }) {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getStats().then(setStats, (e) => setError(e.message));
  }, []);

  if (error) return <div className="page"><p className="error">{error}</p></div>;
  if (!stats) return <div className="page"><p className="muted">Loading the numbers…</p></div>;

  if (stats.hotspots === 0) {
    return (
      <div className="page">
        <h1 className="stat-sentence">No damaged roads reported yet.</h1>
        <button className="btn btn-primary" onClick={() => onNavigate("report")}>Report the first one</button>
      </div>
    );
  }

  const levelRows = ["severe", "moderate", "minor"].map((level) => ({ level, n: stats[level] }));
  const types = Object.entries(stats.damage_by_type);
  const maxType = Math.max(...types.map(([, n]) => n), 1);

  return (
    <div className="page stats-page">
      <h1 className="stat-sentence">
        {stats.hotspots} damaged {stats.hotspots === 1 ? "spot" : "spots"} reported
        in {stats.reports} {stats.reports === 1 ? "photo" : "photos"}.{" "}
        <span style={{ color: LEVELS.severe.color }}>{stats.severe} {stats.severe === 1 ? "needs" : "need"} urgent repair.</span>
      </h1>

      <section className="stat-block">
        <h2>How bad are they?</h2>
        <div className="kerb-bar" role="img"
             aria-label={levelRows.map((r) => `${r.n} ${LEVELS[r.level].name}`).join(", ")}>
          {levelRows.filter((r) => r.n > 0).map((r) => (
            <div key={r.level} style={{ flexGrow: r.n, background: LEVELS[r.level].color }}>
              <span>{r.n} {LEVELS[r.level].name.toLowerCase()}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="stat-block">
        <h2>What kind of damage?</h2>
        <ul className="type-bars">
          {types.map(([label, n]) => (
            <li key={label}>
              <span className="type-name">{damageName(label)}</span>
              <span className="type-track">
                <span style={{ width: `${(n / maxType) * 100}%`, background: DAMAGE[label]?.color }} />
              </span>
              <span className="type-n">{n}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="stat-block">
        <h2>Worst spots right now</h2>
        <ol className="worst">
          {stats.worst_hotspots.map((h) => (
            <li key={h.id}>
              <button className="worst-row" onClick={() => onNavigate("map", h.id)}>
                <span className="worst-where">
                  {h.address || formatCoord(h.lat, h.lng)}
                  <small>
                    {Object.keys(h.damage_counts).map(damageName).join(", ")}, {h.reporter_count}{" "}
                    {h.reporter_count === 1 ? "person" : "people"}
                  </small>
                </span>
                <SeverityScale score={h.severity} level={h.level} size="small" />
              </button>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
