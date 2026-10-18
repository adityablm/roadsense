"""
The RoadSense API: the URLs the website calls.

Run it on your laptop (from the backend folder, with the virtual environment active):
    uvicorn app.main:app --reload
then open http://127.0.0.1:8000/docs to try every URL in your browser.
"""
import io
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg.types.json import Jsonb

from . import config, db, geocode, llm
from .detector import Detector
from .hotspots import assign_report, recluster, remove_report
from .severity import report_severity, severity_level

log = logging.getLogger("roadsense")
detector: Detector | None = None

USER_LABELS = {"pothole", "alligator_crack", "transverse_crack", "longitudinal_crack", "other"}
NOTE_MAX = 80
UNDO_MINUTES = 15            # how long after sending a person can say "this is wrong"
MODEL_INPUT_MAX = 1600       # big photos are decoded smaller: the model only looks at 640x640 anyway
STORED_MAX_SIDE = 1280      # photos are shrunk to at most 1280 px on the long side before saving
STORED_QUALITY = 75         # JPEG quality: small files, still looks fine
POINT = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts (before the yield) and once when it stops (after)."""
    global detector
    db.open_pool()
    try:
        # Creates any missing tables/columns. Safe to run every start ("IF NOT EXISTS").
        with db.connection() as conn:
            conn.execute((config.BACKEND_DIR / "app" / "schema.sql").read_text(encoding="utf-8"))
    except Exception:
        log.exception("Could not apply schema.sql")
    if config.MODEL_PATH.exists():
        detector = Detector(config.MODEL_PATH, config.CONF_THRESHOLD, config.ORT_THREADS,
                            possible_threshold=config.POSSIBLE_THRESHOLD)
        log.info("Model loaded from %s", config.MODEL_PATH)
    else:
        log.warning("No model at %s - photo analysis is off until you add it", config.MODEL_PATH)
    yield
    db.close_pool()


app = FastAPI(title="RoadSense API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,                 # lets the website (a different address) call this API from the browser
    allow_origins=config.FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- helpers
def read_gps(img: Image.Image) -> tuple[float, float] | None:
    """Reads the GPS position a phone camera stores inside the photo (EXIF data), if any."""
    try:
        gps = img.getexif().get_ifd(0x8825)
        if not gps or 2 not in gps or 4 not in gps:
            return None

        def to_degrees(dms):
            d, m, s = (float(v) for v in dms)
            return d + m / 60 + s / 3600

        lat, lng = to_degrees(gps[2]), to_degrees(gps[4])
        if str(gps.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(gps.get(3, "E")).upper().startswith("W"):
            lng = -lng
        return lat, lng
    except Exception:
        return None


def clean_note(text: str | None) -> str:
    """A person's short description, e.g. "water-filled dip near bus stop".
    It later goes into the AI letter prompt, so it is kept short and stripped of control
    characters and of anything that looks like markup or instructions' formatting."""
    text = re.sub(r"[\x00-\x1f\x7f<>{}`]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:NOTE_MAX]


def compress(img: Image.Image) -> tuple[bytes, int, int]:
    small = img.copy()
    small.thumbnail((STORED_MAX_SIDE, STORED_MAX_SIDE))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=STORED_QUALITY, optimize=True)
    return buf.getvalue(), small.width, small.height


def hotspot_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "lat": row["lat"],
        "lng": row["lng"],
        "severity": row["severity"],
        "level": severity_level(row["severity"]),
        "report_count": row["report_count"],
        "reporter_count": row["reporter_count"],
        "damage_counts": row["damage_counts"],
        "status": row["status"],
        "verified": row["verified"],
        "is_demo": row["is_demo"],
        "first_reported": row["first_reported"],
        "last_reported": row["last_reported"],
    }


HOTSPOT_COLUMNS = """id, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng, severity,
    report_count, reporter_count, damage_counts, status, verified, is_demo, first_reported, last_reported"""


# ---------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    """Quick check that the server, database and model are all working."""
    try:
        with db.connection() as conn:
            conn.execute("SELECT 1")
        database = "ok"
    except Exception as exc:
        database = f"error: {exc.__class__.__name__}"
    return {"status": "ok", "database": database, "model_loaded": detector is not None}


@app.post("/api/reports")
def create_report(
    image: UploadFile = File(..., description="A road photo (JPEG, PNG or WebP)"),
    lat: float | None = Form(None, description="Latitude. Optional if the photo has GPS data."),
    lng: float | None = Form(None, description="Longitude. Optional if the photo has GPS data."),
    reporter_id: str | None = Form(None, max_length=64, description="Anonymous id of the person reporting"),
    accept_possible: bool = Form(False, description="Person confirms the AI's low-confidence ('possible') damage"),
    user_label: str | None = Form(None, description="AI found nothing; person reports this damage type themselves"),
    user_note: str | None = Form(None, max_length=300, description="Short description (needed when user_label is 'other')"),
    is_demo: bool = Form(False),
):
    """Analyse one photo. If damage is found, save it and merge it into a hotspot.

    The AI is not the final judge (its recall is about 50%):
    - confident detections (>= CONF_THRESHOLD) are saved directly;
    - weak ones (POSSIBLE_THRESHOLD..CONF_THRESHOLD) are returned as "possible" and only saved
      if the person sends the photo again with accept_possible=true;
    - if the AI finds nothing, the person can report the damage type themselves (user_label).
    Person-decided reports are marked, and their hotspot shows as "not confirmed by the AI"."""
    if detector is None:
        raise HTTPException(503, "The model is not loaded yet (models/roadsense.onnx is missing).")

    data = image.file.read(int(config.MAX_UPLOAD_MB * 1024 * 1024) + 1)
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Photo is larger than {config.MAX_UPLOAD_MB:g} MB.")
    try:
        original = Image.open(io.BytesIO(data))
        gps = read_gps(original)                                   # read GPS before shrinking
        # A 24-megapixel JPEG needs ~70 MB per copy in memory; the free server has 512 MB in total.
        # draft() asks the JPEG decoder for a 2x/4x/8x smaller version directly, which is far cheaper.
        original.draft("RGB", (MODEL_INPUT_MAX, MODEL_INPUT_MAX))
        img = ImageOps.exif_transpose(original).convert("RGB")   # fixes sideways phone photos
        img.thumbnail((MODEL_INPUT_MAX, MODEL_INPUT_MAX))
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "That file is not a photo we can read.")

    location_source = "form"
    if lat is None or lng is None:
        if gps is None:
            raise HTTPException(400, "No location: share your location, or use a photo with GPS data.")
        lat, lng = gps
        location_source = "photo_gps"
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(400, "Latitude/longitude are out of range.")

    found = detector.detect_all(img)
    confident = [d for d in found if d["confidence"] >= config.CONF_THRESHOLD]
    possible = [d for d in found if d["confidence"] < config.CONF_THRESHOLD]
    detections, source = confident, "model"
    if not confident:
        if accept_possible and possible:
            detections, source = [{**d, "possible": True} for d in possible], "user_confirmed"
        elif user_label:
            if user_label not in USER_LABELS:
                raise HTTPException(400, "Unknown damage type.")
            note = clean_note(user_note)
            if user_label == "other" and len(note) < 3:
                raise HTTPException(400, "Please describe the problem in a few words.")
            detections = [{"class_id": None, "label": user_label, "confidence": None, "box": None,
                           **({"note": note} if note else {})}]
            source = "user"

    result = {
        "damage_found": bool(detections),
        "detections": detections,
        "possible_detections": [] if confident else possible,
        "source": source,
        "severity": 0.0,
        "level": "none",
        "lat": lat,
        "lng": lng,
        "location_source": location_source,
        "report_id": None,
        "hotspot_id": None,
        "merged_into_existing": False,
    }
    if not detections:
        return result          # nothing to save: no damage found

    severity = report_severity(detections)
    jpeg, width, height = compress(img)
    with db.connection() as conn:
        row = conn.execute(
            f"""INSERT INTO reports (location, reporter_id, image_jpeg, image_width, image_height,
                                     detections, severity, is_demo, source)
                VALUES ({POINT}, %(reporter)s, %(jpeg)s, %(w)s, %(h)s, %(det)s, %(sev)s, %(demo)s, %(src)s)
                RETURNING id""",
            {"lat": lat, "lng": lng, "reporter": reporter_id, "jpeg": jpeg, "w": width, "h": height,
             "det": Jsonb(detections), "sev": severity, "demo": is_demo, "src": source},
        ).fetchone()
        hotspot_id, merged = assign_report(conn, row["id"], lat, lng, config.HOTSPOT_RADIUS_M)

    result.update(severity=severity, level=severity_level(severity), report_id=row["id"],
                  hotspot_id=hotspot_id, merged_into_existing=merged)
    return result


@app.post("/api/reports/{report_id}/not-damage")
def mark_not_damage(report_id: int, reporter_id: str = Form(..., max_length=64)):
    """The person who just sent a photo says the AI was wrong: there is no damage.
    Only that same person (same anonymous id) can do this, and only within UNDO_MINUTES.
    The photo is kept as a "false alarm" example for retraining, but leaves the map."""
    with db.connection() as conn:
        row = conn.execute(
            """SELECT reporter_id, false_alarm, created_at > now() - make_interval(mins => %s) AS recent
               FROM reports WHERE id = %s""", (UNDO_MINUTES, report_id)).fetchone()
        if not row:
            raise HTTPException(404, "Report not found.")
        if row["false_alarm"]:
            raise HTTPException(409, "This report was already removed.")
        if row["reporter_id"] != reporter_id or not row["recent"]:
            raise HTTPException(403, f"Only the person who sent this photo can remove it, within {UNDO_MINUTES} minutes.")
        hotspot_id = remove_report(conn, report_id)
    return {"report_id": report_id, "removed": True, "hotspot_id": hotspot_id}


@app.get("/api/hotspots")
def list_hotspots(
    min_lat: float = Query(-90), min_lng: float = Query(-180),
    max_lat: float = Query(90), max_lng: float = Query(180),
    include_demo: bool = Query(True),
):
    """All hotspots inside the visible map area (a rectangle), worst first."""
    with db.connection() as conn:
        rows = conn.execute(
            f"""SELECT {HOTSPOT_COLUMNS} FROM hotspots
                WHERE location::geometry && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                  AND (%s OR NOT is_demo)
                ORDER BY severity DESC LIMIT 500""",
            (min_lng, min_lat, max_lng, max_lat, include_demo),
        ).fetchall()
    return [hotspot_summary(r) for r in rows]


@app.get("/api/hotspots/{hotspot_id}")
def get_hotspot(hotspot_id: int):
    """One hotspot with all its reports."""
    with db.connection() as conn:
        row = conn.execute(f"SELECT {HOTSPOT_COLUMNS}, address, complaint_en IS NOT NULL AS has_en, "
                           f"complaint_te IS NOT NULL AS has_te FROM hotspots WHERE id = %s",
                           (hotspot_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Hotspot not found.")
        reports = conn.execute(
            """SELECT id, severity, detections, image_width, image_height, created_at, is_demo, source
               FROM reports WHERE hotspot_id = %s ORDER BY created_at DESC""",
            (hotspot_id,),
        ).fetchall()
    return {
        **hotspot_summary(row),
        "address": row["address"],
        "saved_letters": [lang for lang, has in (("en", row["has_en"]), ("te", row["has_te"])) if has],
        "reports": [{**r, "level": severity_level(r["severity"]),
                     "image_url": f"/api/reports/{r['id']}/image"} for r in reports],
    }


@app.get("/api/reports/{report_id}/image")
def report_image(report_id: int):
    """The saved photo of one report."""
    with db.connection() as conn:
        row = conn.execute("SELECT image_jpeg FROM reports WHERE id = %s", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Report not found.")
    return Response(bytes(row["image_jpeg"]), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/hotspots/{hotspot_id}/complaint")
def complaint(hotspot_id: int, lang: str = Query("en", pattern="^(en|te)$"), refresh: bool = False):
    """Ask Gemini to write a complaint letter for this hotspot (saved, so it's only written once)."""
    column = f"complaint_{lang}"     # safe: lang can only be "en" or "te" (checked above)
    with db.connection() as conn:
        row = conn.execute(f"SELECT {HOTSPOT_COLUMNS}, address, {column} AS letter FROM hotspots WHERE id = %s",
                           (hotspot_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Hotspot not found.")
    if row["letter"] and not refresh:
        return {"hotspot_id": hotspot_id, "lang": lang, "letter": row["letter"], "cached": True}

    address = row["address"] or geocode.reverse_geocode(row["lat"], row["lng"])
    # Facts are phrased the way a resident would describe them, not as database fields,
    # so the letter reads like a citizen wrote it ("I noticed...") rather than a report.
    others = max(0, row["reporter_count"] - 1)
    with db.connection() as conn:
        notes = [r["note"] for r in conn.execute(
            """SELECT DISTINCT d->>'note' AS note FROM reports r, jsonb_array_elements(r.detections) d
               WHERE r.hotspot_id = %s AND d->>'note' IS NOT NULL LIMIT 5""", (hotspot_id,)).fetchall()]
        # How bad the damage LOOKS = its worst photo. The hotspot score is capped below "severe"
        # until a second person reports it; that cap is for ranking the map, not for describing the damage.
        worst_photo = conn.execute(
            "SELECT max(severity) AS s FROM reports WHERE hotspot_id = %s AND NOT false_alarm",
            (hotspot_id,)).fetchone()["s"]
    facts = {
        "address": address or "not available",
        "latitude": round(row["lat"], 6),
        "longitude": round(row["lng"], 6),
        "map_link": f"https://www.openstreetmap.org/?mlat={row['lat']:.6f}&mlon={row['lng']:.6f}#map=19/{row['lat']:.6f}/{row['lng']:.6f}",
        "damage_seen": {("other problem" if label == "other" else label.replace("_", " ")): n
                        for label, n in row["damage_counts"].items()},
        "residents_descriptions_of_other_problems": [clean_note(n) for n in notes],
        "first_noticed_on": row["first_reported"].strftime("%d %B %Y"),
        "how_serious": {"severe": "serious", "moderate": "moderate", "minor": "minor"}[
            severity_level(worst_photo if worst_photo is not None else row["severity"])],
        "other_residents_who_also_reported_it": others,
    }
    try:
        letter = llm.draft_complaint(facts, lang)
    except Exception as exc:
        log.exception("Gemini failed")
        raise HTTPException(502, f"Could not draft the letter: {exc.__class__.__name__}: {exc}")

    with db.connection() as conn:
        conn.execute(
            f"""UPDATE hotspots SET {column} = %s, address = COALESCE(address, %s),
                   status = CASE WHEN status = 'open' THEN 'complaint_drafted' ELSE status END
                WHERE id = %s""",
            (letter, address, hotspot_id),
        )
    return {"hotspot_id": hotspot_id, "lang": lang, "letter": letter, "cached": False}


@app.get("/api/stats")
def stats(include_demo: bool = Query(True)):
    """Numbers for the stats page."""
    with db.connection() as conn:
        totals = conn.execute(
            """SELECT count(*) AS hotspots,
                      coalesce(sum(report_count), 0) AS reports,
                      count(*) FILTER (WHERE severity >= 7) AS severe,
                      count(*) FILTER (WHERE severity >= 4 AND severity < 7) AS moderate,
                      count(*) FILTER (WHERE severity < 4) AS minor
               FROM hotspots WHERE (%s OR NOT is_demo)""",
            (include_demo,),
        ).fetchone()
        by_type = conn.execute(
            """SELECT d->>'label' AS label, count(*) AS n
               FROM reports r, jsonb_array_elements(r.detections) AS d
               WHERE (%s OR NOT r.is_demo) AND NOT r.false_alarm GROUP BY 1 ORDER BY 2 DESC""",
            (include_demo,),
        ).fetchall()
        worst = conn.execute(
            f"""SELECT {HOTSPOT_COLUMNS}, address FROM hotspots WHERE (%s OR NOT is_demo)
                ORDER BY severity DESC, report_count DESC LIMIT 5""",
            (include_demo,),
        ).fetchall()
    return {
        **totals,
        "damage_by_type": {r["label"]: r["n"] for r in by_type},
        "worst_hotspots": [{**hotspot_summary(r), "address": r["address"]} for r in worst],
    }


@app.post("/api/admin/recluster")
def admin_recluster(x_admin_token: str = Header("")):
    """Regroup all reports with DBSCAN. Needs the X-Admin-Token header to match ADMIN_TOKEN."""
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(403, "Admin token missing or wrong.")
    with db.connection() as conn:
        summary = recluster(conn, config.HOTSPOT_RADIUS_M)
    return {**summary, "ran_at": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/admin/missed")
def admin_missed(x_admin_token: str = Header(""), limit: int = Query(200, le=1000)):
    """Photos where the AI and a person disagreed:
    - source 'user' / 'user_confirmed': the AI missed damage or was unsure (false negatives)
    - false_alarm = true: the AI saw damage that wasn't there (false positives, "hard negatives")
    These are exactly the photos the model is bad at, so they are the best data to label and retrain on."""
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(403, "Admin token missing or wrong.")
    with db.connection() as conn:
        rows = conn.execute(
            """SELECT id, source, false_alarm, detections, created_at FROM reports
               WHERE source <> 'model' OR false_alarm ORDER BY created_at DESC LIMIT %s""", (limit,)).fetchall()
    return [{**r, "image_url": f"/api/reports/{r['id']}/image"} for r in rows]
