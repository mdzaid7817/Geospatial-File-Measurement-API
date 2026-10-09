"""End-to-end API tests (need the full dependency set)."""
import pytest
from pyproj import CRS, Transformer

from tests.conftest import PRJ_4326, SQUARE_LONLAT, make_polygon_zip

SAMPLE_KML = open("samples/sample.kml", "rb").read()
SQUARE_AREA = 1_089_991.0   # ellipsoidal reference, m2
SEGMENT_LENGTH = 1_108.2    # 0.01 deg of latitude at 28N, m


def upload_kml(client, data=SAMPLE_KML, name="survey.kml"):
    return client.post("/api/files/", files={"file": (name, data, "application/vnd.google-earth.kml+xml")})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_kml_upload_info_and_measurements(client):
    r = upload_kml(client)
    assert r.status_code == 201
    info = r.json()
    assert info["status"] == "COMPLETED" and info["crs"] == "EPSG:4326"
    assert info["feature_count"] == 5 and info["filename"] == "survey.kml"
    assert any("Label only" in w for w in info["warnings"])

    assert client.get(f"/api/files/{info['id']}/").json()["feature_count"] == 5

    m = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_id = {x["feature_id"]: x for x in m["measurements"]}
    parcel = by_id[0]["measurement"]
    assert parcel["status"] == "MEASURED" and parcel["projected_crs"] == "EPSG:32643"
    assert parcel["area_sq_m"] == pytest.approx(SQUARE_AREA, rel=0.01)   # NOT 0.0001 "degrees squared"
    assert by_id[1]["measurement"]["area_sq_m"] == pytest.approx(915_593, rel=0.01)  # hole subtracted
    assert by_id[2]["measurement"]["length_m"] == pytest.approx(SEGMENT_LENGTH, rel=0.01)
    assert by_id[3]["measurement"]["status"] == "NOT_APPLICABLE"          # point
    assert by_id[4]["geometry_type"] == "GeometryCollection"
    assert by_id[4]["measurement"]["status"] == "UNSUPPORTED"             # graceful, not a crash
    assert m["summary"]["status_counts"]["MEASURED"] == 3


def test_features_endpoint_and_pagination(client):
    fid = upload_kml(client).json()["id"]
    page = client.get(f"/api/files/{fid}/features/", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 5 and len(page["features"]) == 2
    f = page["features"][0]
    assert f["feature_id"] == 1 and f["crs"] == "EPSG:4326" and f["geometry"]["type"] == "Polygon"
    assert f["properties"]["name"].startswith("Parcel B")


def test_shapefile_geographic(client):
    r = client.post("/api/files/", files={"file": ("p.zip", make_polygon_zip(SQUARE_LONLAT), "application/zip")})
    assert r.status_code == 201 and r.json()["file_type"] == "shapefile"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["measurements"][0]["measurement"]["area_sq_m"] == pytest.approx(SQUARE_AREA, rel=0.01)


def test_shapefile_projected_matches_geographic(client):
    to_utm = Transformer.from_crs(4326, 32643, always_xy=True)
    ring = [list(to_utm.transform(x, y)) for x, y in SQUARE_LONLAT]
    prj = CRS.from_epsg(32643).to_wkt(version="WKT1_ESRI")
    r = client.post("/api/files/", files={"file": ("p.zip", make_polygon_zip(ring, prj), "application/zip")})
    assert r.status_code == 201
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["measurements"][0]["measurement"]["area_sq_m"] == pytest.approx(SQUARE_AREA, rel=0.01)


def test_shapefile_without_prj_assumes_wgs84(client):
    data = make_polygon_zip(SQUARE_LONLAT, prj=None, components=("shp", "shx", "dbf"))
    info = client.post("/api/files/", files={"file": ("p.zip", data, "application/zip")}).json()
    assert info["crs"] == "EPSG:4326" and info["crs_assumed"] is True and info["warnings"]


def test_shapefile_without_prj_and_projected_coords_is_rejected(client):
    ring = [[500000, 3000000], [500000, 3000100], [500100, 3000100], [500100, 3000000], [500000, 3000000]]
    data = make_polygon_zip(ring, prj=None, components=("shp", "shx", "dbf"))
    r = client.post("/api/files/", files={"file": ("p.zip", data, "application/zip")})
    assert r.status_code == 422 and r.json()["code"] == "invalid_file"


def test_error_responses(client):
    assert client.post("/api/files/", files={"file": ("a.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post("/api/files/", files={"file": ("a.kml", b"", "text/plain")}).status_code == 422

    bad = upload_kml(client, b"<kml><oops", "bad.kml")
    assert bad.status_code == 422
    fid = bad.json()["file_id"]
    info = client.get(f"/api/files/{fid}/").json()
    assert info["status"] == "FAILED" and info["error"]
    assert client.get(f"/api/files/{fid}/measurements/").status_code == 409

    assert client.get("/api/files/" + "0" * 32 + "/").status_code == 404
    assert client.get("/api/files/..%2F..%2Fetc%2Fpasswd/").status_code == 404

    incomplete = make_polygon_zip(SQUARE_LONLAT, components=("shp", "prj"))
    assert client.post("/api/files/", files={"file": ("p.zip", incomplete, "application/zip")}).status_code == 422


def test_results_survive_new_service_instance(client, tmp_path):
    fid = upload_kml(client).json()["id"]
    from app.config import Settings
    from app.services.file_service import FileService
    from app.services.storage import JsonFileRepository

    fresh = FileService(JsonFileRepository(tmp_path), Settings(data_dir=tmp_path))
    assert fresh.get_info(fid).feature_count == 5
