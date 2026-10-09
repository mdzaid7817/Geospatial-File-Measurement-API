"""Create samples/sample_shapefile.zip (a polygon layer in EPSG:4326) for testing uploads.

Usage:  python scripts/make_sample_shapefile.py
"""
import io
import zipfile
from pathlib import Path

import shapefile  # pyshp

PRJ_4326 = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)

shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf)
w.field("name", "C", size=40)
w.field("owner", "C", size=40)

# NOTE: shapefile outer rings are clockwise.
w.poly([[[77.000, 28.000], [77.000, 28.010], [77.010, 28.010], [77.010, 28.000], [77.000, 28.000]]])
w.record("Parcel A", "Survey Dept")
w.poly([[[77.020, 28.000], [77.020, 28.010], [77.030, 28.010], [77.030, 28.000], [77.020, 28.000]]])
w.record("Parcel B", "City Council")
w.close()

out = Path(__file__).resolve().parent.parent / "samples" / "sample_shapefile.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("parcels.shp", shp.getvalue())
    zf.writestr("parcels.shx", shx.getvalue())
    zf.writestr("parcels.dbf", dbf.getvalue())
    zf.writestr("parcels.prj", PRJ_4326)
print(f"Wrote {out}")
