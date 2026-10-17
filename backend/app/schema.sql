-- RoadSense database tables.
-- Safe to run more than once: "IF NOT EXISTS" skips things that already exist.

-- PostGIS adds map features to PostgreSQL: points, distances, "within 20 metres", clustering.
CREATE EXTENSION IF NOT EXISTS postgis;

-- One row per real-world damaged spot. Many reports can point to the same hotspot.
CREATE TABLE IF NOT EXISTS hotspots (
    id                  BIGSERIAL PRIMARY KEY,
    location            GEOGRAPHY(Point, 4326) NOT NULL,  -- latitude/longitude on the Earth
    report_count        INT  NOT NULL DEFAULT 0,          -- how many photos
    reporter_count      INT  NOT NULL DEFAULT 0,          -- how many different people
    max_report_severity REAL NOT NULL DEFAULT 0,          -- worst single photo (0-10)
    severity            REAL NOT NULL DEFAULT 0,          -- final hotspot score (0-10)
    damage_counts       JSONB NOT NULL DEFAULT '{}',      -- e.g. {"pothole": 3, "alligator_crack": 1}
    status              TEXT NOT NULL DEFAULT 'open',     -- open / complaint_drafted / fixed
    address             TEXT,                             -- filled in from OpenStreetMap when needed
    complaint_en        TEXT,                             -- saved English letter
    complaint_te        TEXT,                             -- saved Telugu letter
    is_demo             BOOLEAN NOT NULL DEFAULT false,   -- true for sample data
    first_reported      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_reported       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- A GIST index makes "find hotspots near this point" fast even with many rows.
CREATE INDEX IF NOT EXISTS hotspots_location_idx ON hotspots USING GIST (location);

-- One row per uploaded photo.
CREATE TABLE IF NOT EXISTS reports (
    id           BIGSERIAL PRIMARY KEY,
    hotspot_id   BIGINT REFERENCES hotspots(id) ON DELETE SET NULL,
    location     GEOGRAPHY(Point, 4326) NOT NULL,
    reporter_id  TEXT,                                -- anonymous browser id, to count different people
    image_jpeg   BYTEA NOT NULL,                      -- small compressed copy of the photo
    image_width  INT NOT NULL,
    image_height INT NOT NULL,
    detections   JSONB NOT NULL,                      -- what the model found (boxes are 0-1 fractions)
    severity     REAL NOT NULL,                       -- 0-10 score for this photo
    is_demo      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reports_location_idx ON reports USING GIST (location);
CREATE INDEX IF NOT EXISTS reports_hotspot_idx ON reports (hotspot_id);

-- Added later: who decided there is damage.
--   'model'          = the AI was confident
--   'user_confirmed' = the AI was unsure (a "possible" detection) and the person confirmed it
--   'user'           = the AI found nothing and the person reported the damage themselves
ALTER TABLE reports ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'model';
-- A hotspot is "verified" when at least one of its photos was confidently detected by the AI.
ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT true;
