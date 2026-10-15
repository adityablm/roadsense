import { useCallback, useEffect, useState } from "react";
import WakingNotice from "./components/WakingNotice.jsx";
import MapPage from "./pages/MapPage.jsx";
import ReportPage from "./pages/ReportPage.jsx";
import StatsPage from "./pages/StatsPage.jsx";

// Pages are chosen by the part of the address after "#", e.g. #/report or #/map?spot=12.
// This needs no extra library and works on any static host without special settings.
function readRoute() {
  const [path, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  const spot = new URLSearchParams(query).get("spot");
  return { page: ["map", "report", "stats"].includes(path) ? path : "map", spot: spot ? Number(spot) : null };
}

const NAV = [
  { page: "map", label: "Map" },
  { page: "report", label: "Report damage", short: "Report" },
  { page: "stats", label: "Numbers" },
];

export default function App() {
  const [route, setRoute] = useState(readRoute);

  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = useCallback((page, spot = null) => {
    window.location.hash = `/${page}${spot ? `?spot=${spot}` : ""}`;
  }, []);

  const selectSpot = useCallback((id) => navigate("map", id), [navigate]);

  return (
    <div className="app">
      <header className="topbar">
        <a className="wordmark" href="#/map" aria-label="RoadSense, go to the map">
          Road<span>Sense</span>
        </a>
        <nav aria-label="Main">
          {NAV.map((item) => (
            <a key={item.page} href={`#/${item.page}`} aria-current={route.page === item.page ? "page" : undefined}>
              {item.short ? (
                <>
                  <span className="nav-long">{item.label}</span>
                  <span className="nav-short">{item.short}</span>
                </>
              ) : item.label}
            </a>
          ))}
        </nav>
      </header>
      <div className="kerb" aria-hidden="true" />
      <WakingNotice />

      <main className="main">
        {route.page === "map" && <MapPage selectedId={route.spot} onSelect={selectSpot} onNavigate={navigate} />}
        {route.page === "report" && <ReportPage onNavigate={navigate} />}
        {route.page === "stats" && <StatsPage onNavigate={navigate} />}
      </main>
    </div>
  );
}
