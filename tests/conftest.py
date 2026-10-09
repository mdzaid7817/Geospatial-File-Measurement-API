import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_file_service
from app.config import Settings
from app.main import create_app
from app.services.file_service import FileService
from app.services.storage import JsonFileRepository


@pytest.fixture
def client(tmp_path):
    app = create_app()
    settings = Settings(data_dir=tmp_path)
    service = FileService(JsonFileRepository(tmp_path), settings)
    app.dependency_overrides[get_file_service] = lambda: service
    return TestClient(app)


PRJ_4326 = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)

# Clockwise square of 0.01 x 0.01 degrees at ~28N (reference area ~1,089,991 m2)
SQUARE_LONLAT = [[77.0, 28.0], [77.0, 28.01], [77.01, 28.01], [77.01, 28.0], [77.0, 28.0]]


def make_polygon_zip(ring, prj=PRJ_4326, components=("shp", "shx", "dbf", "prj")) -> bytes:
    import shapefile  # pyshp

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf)
    w.field("name", "C", size=40)
    w.poly([ring])
    w.record("Parcel")
    w.close()
    parts = {"shp": shp.getvalue(), "shx": shx.getvalue(), "dbf": dbf.getvalue()}
    if prj:
        parts["prj"] = prj.encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ext in components:
            if ext in parts:
                zf.writestr(f"parcels.{ext}", parts[ext])
    return buf.getvalue()
