# Geospatial File Measurement API

Upload a **Shapefile (`.zip`)** or **KML** file and get back its features with **area and length in metres**.
Built with FastAPI, shapely, pyproj, pyshp and lxml (no GDAL needed).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

- Interactive docs and test page: http://127.0.0.1:8000/docs
- Run tests: `pytest -q`
- Sample files: `samples/sample.kml`, `samples/accuracy_test.kml`.
  For a Shapefile run `python scripts/make_sample_shapefile.py` (creates `samples/sample_shapefile.zip`).

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/files/` | Upload a `.kml` or a `.zip` with a Shapefile (`.shp`, `.shx`, `.dbf`, optional `.prj`) |
| GET | `/api/files/{id}/` | File info |
| GET | `/api/files/{id}/measurements/` | Measurements per feature, plus a summary |
| GET | `/api/files/{id}/features/` | Extracted features: geometry, CRS, properties (extra) |

The last two accept `limit` and `offset`. Errors look like `{"detail": "...", "code": "..."}`:
`415` wrong file type, `413` too large, `422` unreadable file (a `FAILED` record is kept, see `file_id`),
`404` unknown id, `409` file failed processing.

```bash
curl -F "file=@samples/sample.kml" http://127.0.0.1:8000/api/files/
curl http://127.0.0.1:8000/api/files/<id>/measurements/
```

**Upload response**

```json
{
  "id": "3b6202ed98cc4fecb270007e71cd53e7",
  "filename": "sample.kml",
  "status": "COMPLETED",
  "feature_count": 5,
  "crs": "EPSG:4326"
}
```

**Measurements response** (shortened)

```json
{
  "summary": {
    "status_counts": {"MEASURED": 3, "NOT_APPLICABLE": 1, "UNSUPPORTED": 1, "ERROR": 0},
    "total_area_sq_m": 2005921.5184,
    "total_length_m": 1108.281
  },
  "measurements": [
    {"feature_id": 0, "geometry_type": "Polygon", "crs": "EPSG:4326",
     "measurement": {"status": "MEASURED", "area_sq_m": 1090165.1617,
                     "perimeter_m": 4183.8708, "projected_crs": "EPSG:32643"}},
    {"feature_id": 3, "geometry_type": "Point", "crs": "EPSG:4326",
     "measurement": {"status": "NOT_APPLICABLE", "message": "No measurement defined for Point"}}
  ]
}
```

Each feature has a status: `MEASURED`, `NOT_APPLICABLE` (points), `UNSUPPORTED` (e.g. mixed geometry
collections) or `ERROR`. One bad feature never fails the whole file.

## Architecture

```
app/
├── main.py, config.py
├── api/routes/files.py     # HTTP endpoints only
├── schemas/files.py        # request/response models
├── services/               # file_service (flow), measurement, crs, storage
├── parsers/                # kml_parser, shapefile_parser, safe zip extraction
└── core/                   # errors and small helpers
```

**File processing:** check the extension, save the upload to a temp file with a size limit, parse the
features (KML or Shapefile), work out the CRS, measure each feature, save the result as JSON in `data/`.

**Measurement:** geometry, then WGS 84, then the UTM zone picked from its centroid, then measure in metres.
Polygons get area and perimeter (holes subtracted), lines get length, points get nothing.
Nothing is ever measured in degrees.

**CRS handling:** KML is always EPSG:4326. A Shapefile uses its `.prj`. With no `.prj`, EPSG:4326 is assumed
only if the coordinates look like lon/lat (flagged in the response); otherwise the upload is rejected.

## Design decisions

- **FastAPI** over Django: lighter, with automatic API docs.
- **pyshp + lxml** instead of GeoPandas/GDAL: easy install everywhere. New formats can be added as new parsers.
- **UTM per feature** instead of one fixed projection: accurate for most local features. Alternatives:
  equal-area projection or geodesic maths.
- **Always go via WGS 84**: one path for all inputs, and it handles Web Mercator, which distorts area.
- **JSON file per upload** instead of a database: no setup and survives restarts.
- **Safe uploads**: zip-bomb limits, no path traversal, XML entity expansion disabled.

## Testing and accuracy

20 automated tests cover KML and Shapefile upload, geographic and projected CRS, a missing `.prj`,
polygon holes, unsupported geometry, error responses and zip safety.

Results were also checked against an independent calculation of the exact WGS 84 ellipsoid area/length
(no shapely or pyproj), using `samples/sample.kml` and `samples/accuracy_test.kml`:

| Test shape | API result | Reference | Difference |
|---|---|---|---|
| Delhi parcel, 28°N (UTM 43N) | 1,090,165 m² | 1,089,991 m² | +0.016% |
| Buenos Aires, southern hemisphere (UTM 21S) | 1,017,129 m² | 1,017,533 m² | −0.040% |
| London, western longitude (UTM 30N) | 772,649 m² | 772,496 m² | +0.020% |
| Tromsø, 69.6°N (UTM 34N) | 432,754 m² | 433,034 m² | −0.065% |
| Polygon across the 72°E zone boundary | 2,182,924 m² | 2,179,983 m² | +0.135% |
| London north-south line | 1,112.69 m | 1,112.6 m | +0.008% |
| **Large box spanning two UTM zones** | 552,298,206,524 m² | 548,733,680,392 m² | **+0.650%** |

Small local features are within about 0.15% of the exact value. The small differences are the normal UTM
scale effect and grow with distance from the zone's central meridian.

## Limitations

- **Large features lose accuracy.** The UTM zone is chosen from the centroid, so a shape spanning several
  zones is measured in one of them (the two-zone test box above is 0.65% off). Features crossing the
  antimeridian are also affected.
- Z/M values are dropped (measurements are planar).
- KMZ and other formats are not supported yet.
- Results are stored as one JSON file per upload, so very large files are loaded fully on each read.

## Learnings

- CRS handling is the hard part: KML is always WGS 84, but Shapefiles may have a missing or differently
  formatted `.prj`.
- Measuring in degrees gives meaningless numbers (about 0.0001 instead of ~1.09 million m² for the sample).
- Web Mercator is projected but distorts area, so it should never be used for measuring.
- Reporting a status per feature keeps the API robust with messy files.
- Checking results against an independent calculation showed where UTM is accurate and where it is not.
- Dependencies change: a newer shapely deprecated `shapely.ops.transform`, so I switched to `shapely.transform`.

## Future scope

- Geodesic measurement option (removes the UTM zone limitation for large features)
- Background processing for large files, with a `PROCESSING` status
- PostGIS storage for spatial queries
- More formats: KMZ, GeoJSON, GeoPackage
- Other units (hectares, acres), auth, rate limits, file cleanup