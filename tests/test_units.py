"""Dependency-light unit tests (KML parser, zip safety, helpers)."""
import io
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.core.exceptions import InvalidFileError
from app.core.geo import looks_like_lonlat, utm_epsg_for
from app.core.serialization import to_jsonable
from app.parsers.archive import extract_shapefile
from app.parsers.kml_parser import KMLParser

KML = """<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
 <Placemark><name>P</name>
  <ExtendedData><Data name="k"><value>v</value></Data></ExtendedData>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>
    77,28,0 77,28.01,0 77.01,28.01,0 77.01,28,0
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
 <Placemark><name>L</name><LineString><coordinates>1, 2, 0 3, 4, 0</coordinates></LineString></Placemark>
 <Placemark><name>Bad</name><LineString><coordinates>oops</coordinates></LineString></Placemark>
 <Placemark><name>Mixed</name><MultiGeometry>
   <Point><coordinates>1,1</coordinates></Point>
   <LineString><coordinates>1,1 2,2</coordinates></LineString></MultiGeometry></Placemark>
 <Placemark><name>NoGeom</name></Placemark>
</Document></kml>"""


def _parse(text: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.kml"
        p.write_text(text, encoding="utf-8")
        return KMLParser().parse(p)


def test_kml_features_and_properties():
    parsed = _parse(KML)
    assert parsed.crs_definition == "EPSG:4326"
    assert [f.index for f in parsed.features] == [0, 1, 2, 3]
    poly = parsed.features[0]
    assert poly.geometry["type"] == "Polygon"
    ring = poly.geometry["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5  # auto-closed
    assert poly.properties == {"name": "P", "k": "v"}
    assert parsed.features[1].geometry["coordinates"] == [[1.0, 2.0], [3.0, 4.0]]  # "lon, lat" tolerated


def test_kml_bad_and_mixed_and_skipped():
    parsed = _parse(KML)
    assert parsed.features[2].geometry is None and "Invalid coordinate" in parsed.features[2].problem
    assert parsed.features[3].geometry["type"] == "GeometryCollection"
    assert any("NoGeom" in w for w in parsed.warnings)


def test_kml_rejects_non_kml():
    with pytest.raises(InvalidFileError):
        _parse("<html></html>")
    with pytest.raises(InvalidFileError):
        _parse("not xml at all")


def test_kml_entities_not_expanded():
    xxe = ('<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           '<kml><Placemark><name>&x;</name><Point><coordinates>1,2</coordinates></Point></Placemark></kml>')
    parsed = _parse(xxe)
    assert "root:" not in parsed.features[0].properties.get("name", "")


def _zip(entries: dict[str, bytes]) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "u.zip"
    with zipfile.ZipFile(p, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return p


def _extract(entries, **kw):
    dest = Path(tempfile.mkdtemp())
    limits = dict(max_entries=50, max_uncompressed_bytes=10_000)
    limits.update(kw)
    return extract_shapefile(_zip(entries), dest, **limits), dest


def test_zip_extracts_to_fixed_names_and_ignores_traversal_names():
    (path, warnings), dest = _extract(
        {"../../evil/a.shp": b"1", "../../evil/a.shx": b"2", "../../evil/a.dbf": b"3", "a.prj": b"x"}
    )
    assert path == dest / "layer.shp" and path.read_bytes() == b"1"
    assert sorted(p.name for p in dest.iterdir()) == ["layer.dbf", "layer.shp", "layer.shx"]
    assert not (dest.parent.parent / "evil").exists()


def test_zip_missing_component_and_no_shp_and_bad_zip():
    with pytest.raises(InvalidFileError, match=r"missing.*\.dbf"):
        _extract({"a.shp": b"1", "a.shx": b"2"})
    with pytest.raises(InvalidFileError, match="does not contain a .shp"):
        _extract({"readme.txt": b"hi"})
    bad = Path(tempfile.mkdtemp()) / "b.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(InvalidFileError, match="Cannot read ZIP"):
        extract_shapefile(bad, Path(tempfile.mkdtemp()), max_entries=5, max_uncompressed_bytes=10)


def test_zip_limits():
    with pytest.raises(InvalidFileError, match="uncompressed"):
        _extract({"a.shp": b"x" * 9000, "a.shx": b"x" * 9000, "a.dbf": b"1"})
    with pytest.raises(InvalidFileError, match="too many"):
        _extract({f"f{i}.txt": b"1" for i in range(10)}, max_entries=5)


def test_zip_multiple_shapefiles_warns():
    (path, warnings), _ = _extract(
        {f"{n}.{e}": b"1" for n in ("a", "b") for e in ("shp", "shx", "dbf")}
    )
    assert warnings and "only 'a'" in warnings[0]


def test_utm_zone_selection():
    assert utm_epsg_for(77.005, 28.005) == 32643   # Delhi: 43N
    assert utm_epsg_for(-58.4, -34.6) == 32721     # Buenos Aires: 21S
    assert utm_epsg_for(-0.1, 51.5) == 32630       # London: 30N
    assert utm_epsg_for(179.9, 10) == 32660 and utm_epsg_for(-179.9, 10) == 32601
    assert utm_epsg_for(190, 10) == utm_epsg_for(-170, 10)  # 0-360 longitudes
    assert utm_epsg_for(0, 89) == 32661 and utm_epsg_for(0, -85) == 32761


def test_lonlat_detection():
    assert looks_like_lonlat((-10, -10, 10, 10))
    assert not looks_like_lonlat((500000, 3000000, 500100, 3000100))


def test_to_jsonable():
    from datetime import date
    from decimal import Decimal

    out = to_jsonable({"d": date(2024, 1, 2), "n": float("nan"), "x": Decimal("1.5"), "b": b"hi", 3: (1, 2)})
    assert out == {"d": "2024-01-02", "n": None, "x": 1.5, "b": "hi", "3": [1, 2]}
