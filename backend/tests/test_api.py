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


def test_bad_inputs_are_rejected(client):
    c, _ = client
    r = c.post("/api/reports", files={"image": ("x.jpg", b"not an image", "image/jpeg")},
               data={"lat": "17.3", "lng": "78.4"})
    assert r.status_code == 400
    r = c.post("/api/reports", files={"image": photo()})          # no location, no GPS in photo
    assert r.status_code == 400 and "location" in r.json()["detail"].lower()
    assert c.get("/api/hotspots/999999").status_code == 404
