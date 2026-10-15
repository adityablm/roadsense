"""
Merging duplicate reports into hotspots. This is the "hard problem" of the project.

The same pothole gets photographed by different people, from different angles,
and phone GPS can be off by 5-15 metres. Two layers handle this:

1. assign_report()  - runs for every new photo. If a hotspot already exists
   within HOTSPOT_RADIUS_M metres, the photo joins it; otherwise a new hotspot
   is created. A database lock makes sure two photos arriving at the same moment
   can't both create a new hotspot for the same spot.

2. recluster()      - an admin action that regroups ALL reports from scratch with
   DBSCAN clustering (PostGIS function ST_ClusterDBSCAN). It fixes cases the fast
   path got wrong, e.g. a hotspot that drifted, or two hotspots that should be one.
   Existing hotspot rows (with their status and saved letters) are reused wherever possible.
"""
import math
from collections import Counter, defaultdict

from psycopg.types.json import Jsonb

from .severity import hotspot_severity

LOCK_KEY = 4242  # any fixed number; everyone who wants to change hotspots waits for this lock

POINT = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"


def assign_report(conn, report_id: int, lat: float, lng: float, radius_m: float) -> tuple[int, bool]:
    """Puts one report into a hotspot. Returns (hotspot_id, merged_into_existing)."""
    params = {"lat": lat, "lng": lng, "r": radius_m}
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        cur.execute(
            f"""SELECT id FROM hotspots
                WHERE ST_DWithin(location, {POINT}, %(r)s)
                ORDER BY ST_Distance(location, {POINT})
                LIMIT 1""",
            params,
        )
        row = cur.fetchone()
        if row:
            hotspot_id, merged = row["id"], True
        else:
            cur.execute(f"INSERT INTO hotspots (location) VALUES ({POINT}) RETURNING id", params)
            hotspot_id, merged = cur.fetchone()["id"], False
        cur.execute("UPDATE reports SET hotspot_id = %s WHERE id = %s", (hotspot_id, report_id))
        refresh_hotspot(cur, hotspot_id)
        # The situation changed, so any saved complaint letter is out of date.
        cur.execute("UPDATE hotspots SET complaint_en = NULL, complaint_te = NULL WHERE id = %s", (hotspot_id,))
    return hotspot_id, merged


def refresh_hotspot(cur, hotspot_id: int) -> None:
    """Recalculates a hotspot's numbers from the reports that belong to it."""
    cur.execute(
        """SELECT count(*) AS n,
                  count(DISTINCT COALESCE(reporter_id, 'report-' || id)) AS reporters,
                  max(severity) AS max_sev,
                  min(created_at) AS first_at, max(created_at) AS last_at,
                  bool_and(is_demo) AS demo,
                  ST_Y(ST_Centroid(ST_Collect(location::geometry))) AS lat,
                  ST_X(ST_Centroid(ST_Collect(location::geometry))) AS lng
           FROM reports WHERE hotspot_id = %s""",
        (hotspot_id,),
    )
    s = cur.fetchone()
    if not s["n"]:
        cur.execute("DELETE FROM hotspots WHERE id = %s", (hotspot_id,))
        return
    cur.execute(
        """SELECT d->>'label' AS label, count(*) AS n
           FROM reports r, jsonb_array_elements(r.detections) AS d
           WHERE r.hotspot_id = %s GROUP BY 1""",
        (hotspot_id,),
    )
    damage = {row["label"]: row["n"] for row in cur.fetchall()}
    cur.execute(
        f"""UPDATE hotspots SET
                location = {POINT},
                report_count = %(n)s, reporter_count = %(reporters)s,
                max_report_severity = %(max_sev)s, severity = %(sev)s,
                damage_counts = %(damage)s, is_demo = %(demo)s,
                first_reported = %(first_at)s, last_reported = %(last_at)s
            WHERE id = %(id)s""",
        {**s, "sev": hotspot_severity(s["max_sev"], s["reporters"]),
         "damage": Jsonb(damage), "id": hotspot_id},
    )


def recluster(conn, radius_m: float) -> dict:
    """Regroups every report with DBSCAN. Returns a small summary."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        cur.execute("SELECT count(*) AS n FROM hotspots")
        before = cur.fetchone()["n"]
        cur.execute("SELECT avg(ST_Y(location::geometry)) AS lat FROM reports")
        avg_lat = cur.fetchone()["lat"]
        if avg_lat is None:
            return {"reports": 0, "hotspots_before": before, "hotspots_after": before}

        # ST_ClusterDBSCAN works on flat map coordinates (EPSG:3857, in "metres").
        # That map stretches distances by 1/cos(latitude), so the radius is stretched the same way.
        eps = radius_m / math.cos(math.radians(avg_lat))
        cur.execute(
            """SELECT id, hotspot_id,
                      ST_ClusterDBSCAN(ST_Transform(location::geometry, 3857), eps := %s, minpoints := 1)
                          OVER () AS cluster
               FROM reports""",
            (eps,),
        )
        clusters = defaultdict(list)
        for row in cur.fetchall():
            clusters[row["cluster"]].append(row)

        used = set()
        for members in sorted(clusters.values(), key=len, reverse=True):
            # Reuse the old hotspot most of these reports were already in (keeps status and letters).
            votes = Counter(m["hotspot_id"] for m in members if m["hotspot_id"] is not None)
            hotspot_id = next((h for h, _ in votes.most_common() if h not in used), None)
            if hotspot_id is None:
                cur.execute(
                    "INSERT INTO hotspots (location) SELECT location FROM reports WHERE id = %s RETURNING id",
                    (members[0]["id"],),
                )
                hotspot_id = cur.fetchone()["id"]
            used.add(hotspot_id)
            cur.execute("UPDATE reports SET hotspot_id = %s WHERE id = ANY(%s)",
                        (hotspot_id, [m["id"] for m in members]))

        cur.execute("DELETE FROM hotspots WHERE NOT (id = ANY(%s))", (list(used),))
        for hotspot_id in used:
            refresh_hotspot(cur, hotspot_id)
        return {"reports": sum(len(m) for m in clusters.values()),
                "hotspots_before": before, "hotspots_after": len(used)}
