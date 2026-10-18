"""
End-to-end test of the API against a REAL PostgreSQL + PostGIS database,
using a tiny fake model that always "finds" the same pothole.

It only runs if you set TEST_DATABASE_URL to an EMPTY test database
(it deletes everything in it). It is skipped otherwise.
"""
import io
import os

import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")


def make_fake_model(path, rows):
    """A minimal ONNX model with the same input/output shapes as the real one."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    out = np.zeros((1, 300, 6), dtype=np.float32)
    out[0, : len(rows)] = rows
    graph = helper.make_graph(
        [helper.make_node("Identity", ["const"], ["output0"])],
        "fake",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 300, 6])],
        initializer=[numpy_helper.from_array(out, "const")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9          # a format version every onnxruntime release can read
    onnx.save(model, path)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    model = tmp_path_factory.mktemp("m") / "fake.onnx"
    make_fake_model(model, [[200, 300, 440, 440, 0.85, 3]])   # one big pothole
    os.environ.update(DATABASE_URL=TEST_DB, MODEL_PATH=str(model), ADMIN_TOKEN="test-admin",
                      HOTSPOT_RADIUS_M="20")
    import psycopg
    from importlib import reload
    from app import config, main
    reload(config)
    reload(main)
    schema = (config.BACKEND_DIR / "app" / "schema.sql").read_text()
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS reports, hotspots CASCADE")
        conn.execute(schema)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c, main


def photo():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1280, 720), (90, 90, 90)).save(buf, "JPEG")
    return ("road.jpg", buf.getvalue(), "image/jpeg")


def post(c, lat, lng, who):
    r = c.post("/api/reports", files={"image": photo()},
               data={"lat": str(lat), "lng": str(lng), "reporter_id": who})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    c, _ = client
    assert c.get("/api/health").json() == {"status": "ok", "database": "ok", "model_loaded": True}


def test_reports_merge_into_hotspots(client):
    c, _ = client
    a = post(c, 17.385000, 78.486700, "alice")
    assert a["damage_found"] and a["detections"][0]["label"] == "pothole"
    assert not a["merged_into_existing"]

    b = post(c, 17.385080, 78.486720, "bob")          # ~9 m away -> same hotspot
    assert b["merged_into_existing"] and b["hotspot_id"] == a["hotspot_id"]

    far = post(c, 17.390000, 78.490000, "carol")      # ~650 m away -> new hotspot
    assert not far["merged_into_existing"] and far["hotspot_id"] != a["hotspot_id"]

    h = c.get(f"/api/hotspots/{a['hotspot_id']}").json()
    assert h["report_count"] == 2 and h["reporter_count"] == 2
    assert h["damage_counts"] == {"pothole": 2}
    assert h["severity"] > a["severity"]               # confirmed by 2 people -> higher score
    img = c.get(h["reports"][0]["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    in_box = c.get("/api/hotspots", params=dict(min_lat=17.38, min_lng=78.48, max_lat=17.386, max_lng=78.487)).json()
    assert [x["id"] for x in in_box] == [a["hotspot_id"]]


def test_single_reporter_stays_below_severe(client):
    c, _ = client
    r = None
    for _ in range(3):                                # same person, same spot, 3 times
        r = post(c, 12.971600, 77.594600, "dave")
    h = c.get(f"/api/hotspots/{r['hotspot_id']}").json()
    assert h["report_count"] == 3 and h["reporter_count"] == 1 and h["severity"] < 7


def test_stats(client):
    c, _ = client
    s = c.get("/api/stats").json()
    assert s["hotspots"] == 3 and s["reports"] == 6
    assert s["damage_by_type"] == {"pothole": 6}
    assert len(s["worst_hotspots"]) == 3


def test_recluster_fixes_a_split_hotspot(client):
    c, main = client
    # Force a bad split: move one report of the first hotspot into its own hotspot by hand.
    from app import db
    with db.connection() as conn:
        first = conn.execute("SELECT hotspot_id FROM reports ORDER BY id LIMIT 1").fetchone()["hotspot_id"]
        new = conn.execute("INSERT INTO hotspots (location) SELECT location FROM reports WHERE id = 2 "
                           "RETURNING id").fetchone()["id"]
        conn.execute("UPDATE reports SET hotspot_id = %s WHERE id = 2", (new,))
    assert c.get("/api/stats").json()["hotspots"] == 4

    assert c.post("/api/admin/recluster").status_code == 403
    r = c.post("/api/admin/recluster", headers={"X-Admin-Token": "test-admin"}).json()
    assert r["hotspots_before"] == 4 and r["hotspots_after"] == 3
    h = c.get(f"/api/hotspots/{first}").json()          # the original hotspot id survived
    assert h["report_count"] == 2


def test_complaint_letter_uses_facts_and_is_saved(client, monkeypatch):
    c, main = client
    seen = {}

    def fake_draft(facts, lang):
        seen.update(facts=facts, lang=lang)
        return f"Dear Sir/Madam ({lang})"

    monkeypatch.setattr(main.llm, "draft_complaint", fake_draft)
    monkeypatch.setattr(main.geocode, "reverse_geocode", lambda lat, lng: "Test Road, Hyderabad")
    hid = c.get("/api/stats").json()["worst_hotspots"][0]["id"]

    first = c.post(f"/api/hotspots/{hid}/complaint", params={"lang": "te"}).json()
    assert first == {"hotspot_id": hid, "lang": "te", "letter": "Dear Sir/Madam (te)", "cached": False}
    assert seen["facts"]["address"] == "Test Road, Hyderabad"
    assert seen["facts"]["damage_seen"] == {"pothole": 2}
    assert seen["facts"]["other_residents_who_also_reported_it"] == 1   # 2 people reported it: you + 1 other
    assert "severity" not in str(seen["facts"])                         # no internal score in the letter

    again = c.post(f"/api/hotspots/{hid}/complaint", params={"lang": "te"}).json()
    assert again["cached"] is True
    h = c.get(f"/api/hotspots/{hid}").json()
    assert h["status"] == "complaint_drafted" and h["saved_letters"] == ["te"]
    assert c.post(f"/api/hotspots/{hid}/complaint", params={"lang": "fr"}).status_code == 422


def test_letter_describes_the_damage_not_the_report_count(client, monkeypatch):
    # dave's spot: one person, a big confident pothole. The map caps the spot below "severe"
    # until a second person confirms it, but the letter must still call the damage serious.
    c, main = client
    seen = {}
    monkeypatch.setattr(main.llm, "draft_complaint", lambda facts, lang: seen.update(facts) or "Dear Sir")
    monkeypatch.setattr(main.geocode, "reverse_geocode", lambda lat, lng: "MG Road")
    r = post(c, 12.971600, 77.594600, "dave")
    h = c.get(f"/api/hotspots/{r['hotspot_id']}").json()
    assert h["reporter_count"] == 1 and h["severity"] < 7 and r["severity"] >= 7
    c.post(f"/api/hotspots/{r['hotspot_id']}/complaint", params={"lang": "en", "refresh": "true"})
    assert seen["how_serious"] == "serious"


def test_bad_inputs_are_rejected(client):
    c, _ = client
    r = c.post("/api/reports", files={"image": ("x.jpg", b"not an image", "image/jpeg")},
               data={"lat": "17.3", "lng": "78.4"})
    assert r.status_code == 400
    r = c.post("/api/reports", files={"image": photo()})          # no location, no GPS in photo
    assert r.status_code == 400 and "location" in r.json()["detail"].lower()
    assert c.get("/api/hotspots/999999").status_code == 404


# ---------------- the person decides when the AI is unsure or misses damage
def test_possible_damage_is_only_saved_when_confirmed(client, monkeypatch):
    c, main = client
    weak = [{"class_id": 3, "label": "pothole", "confidence": 0.2, "box": [0.1, 0.5, 0.4, 0.8]}]
    monkeypatch.setattr(main.detector, "detect_all", lambda img: weak)
    first = post(c, 13.0, 80.0, "erin")
    assert not first["damage_found"] and first["report_id"] is None
    assert first["possible_detections"] == weak

    r = c.post("/api/reports", files={"image": photo()},
               data={"lat": "13.0", "lng": "80.0", "reporter_id": "erin", "accept_possible": "true"})
    body = r.json()
    assert body["damage_found"] and body["source"] == "user_confirmed"
    h = c.get(f"/api/hotspots/{body['hotspot_id']}").json()
    assert h["verified"] is False and h["reports"][0]["source"] == "user_confirmed"


def test_person_can_report_what_the_ai_missed(client, monkeypatch):
    c, main = client
    monkeypatch.setattr(main.detector, "detect_all", lambda img: [])
    nothing = post(c, 14.0, 81.0, "frank")
    assert not nothing["damage_found"] and nothing["possible_detections"] == []

    # "Other" needs a description
    r = c.post("/api/reports", files={"image": photo()},
               data={"lat": "14.0", "lng": "81.0", "reporter_id": "frank", "user_label": "other"})
    assert r.status_code == 400
    r = c.post("/api/reports", files={"image": photo()},
               data={"lat": "14.0", "lng": "81.0", "reporter_id": "frank", "user_label": "other",
                     "user_note": "  sunken manhole <script>alert(1)</script>\n near bus stop " + "x" * 200})
    body = r.json()
    assert body["damage_found"] and body["source"] == "user"
    note = body["detections"][0]["note"]
    assert "<" not in note and "\n" not in note and len(note) <= 80
    assert body["detections"][0]["box"] is None
    assert body["severity"] < 4                                   # a single unconfirmed report stays minor

    h = c.get(f"/api/hotspots/{body['hotspot_id']}").json()
    assert h["verified"] is False and h["damage_counts"] == {"other": 1}

    # a confident AI detection at the same spot makes it verified
    monkeypatch.setattr(main.detector, "detect_all",
                        lambda img: [{"class_id": 3, "label": "pothole", "confidence": 0.9, "box": [0.1, 0.5, 0.5, 0.9]}])
    later = post(c, 14.00005, 81.00005, "gina")
    assert later["hotspot_id"] == body["hotspot_id"]
    assert c.get(f"/api/hotspots/{body['hotspot_id']}").json()["verified"] is True

    # when the AI is confident, a person's label is ignored
    r = c.post("/api/reports", files={"image": photo()},
               data={"lat": "15.0", "lng": "82.0", "user_label": "dragon"})
    assert r.status_code == 200 and r.json()["source"] == "model"
    # when the AI finds nothing, an unknown label is rejected
    monkeypatch.setattr(main.detector, "detect_all", lambda img: [])
    r = c.post("/api/reports", files={"image": photo()},
               data={"lat": "15.0", "lng": "82.0", "user_label": "dragon"})
    assert r.status_code == 400


def test_admin_missed_list(client):
    c, _ = client
    assert c.get("/api/admin/missed").status_code == 403
    rows = c.get("/api/admin/missed", headers={"X-Admin-Token": "test-admin"}).json()
    assert {r["source"] for r in rows} == {"user", "user_confirmed"}


def test_sender_can_mark_a_false_alarm(client):
    c, _ = client
    r = post(c, 16.0, 79.0, "hana")
    hid, rid = r["hotspot_id"], r["report_id"]
    assert c.post(f"/api/reports/{rid}/not-damage", data={"reporter_id": "someone-else"}).status_code == 403

    ok = c.post(f"/api/reports/{rid}/not-damage", data={"reporter_id": "hana"})
    assert ok.status_code == 200 and ok.json()["hotspot_id"] == hid
    assert c.get(f"/api/hotspots/{hid}").status_code == 404          # its only report is gone, so the spot is too
    assert c.post(f"/api/reports/{rid}/not-damage", data={"reporter_id": "hana"}).status_code == 409

    rows = c.get("/api/admin/missed", headers={"X-Admin-Token": "test-admin"}).json()
    assert any(x["id"] == rid and x["false_alarm"] for x in rows)    # kept for retraining

    # a recluster must not bring it back
    c.post("/api/admin/recluster", headers={"X-Admin-Token": "test-admin"})
    assert all(h["id"] != hid for h in c.get("/api/hotspots").json())


def test_false_alarm_only_removes_that_photo_and_has_a_time_limit(client):
    c, main = client
    a = post(c, 18.0, 77.0, "ivan")
    b = post(c, 18.00005, 77.00005, "jade")
    assert a["hotspot_id"] == b["hotspot_id"]
    c.post(f"/api/reports/{b['report_id']}/not-damage", data={"reporter_id": "jade"})
    h = c.get(f"/api/hotspots/{a['hotspot_id']}").json()
    assert h["report_count"] == 1 and h["reporter_count"] == 1        # the other person's report stays

    from app import db
    with db.connection() as conn:
        conn.execute("UPDATE reports SET created_at = now() - interval '1 hour' WHERE id = %s", (a["report_id"],))
    late = c.post(f"/api/reports/{a['report_id']}/not-damage", data={"reporter_id": "ivan"})
    assert late.status_code == 403


def test_big_photos_are_decoded_small(client):
    c, _ = client
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (6000, 4000), (90, 90, 90)).save(buf, "JPEG")
    r = c.post("/api/reports", files={"image": ("big.jpg", buf.getvalue(), "image/jpeg")},
               data={"lat": "19.0", "lng": "76.0", "reporter_id": "kim"})
    assert r.status_code == 200 and r.json()["damage_found"]
