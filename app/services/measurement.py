"""Measurement engine.

Strategy (per feature):
    source CRS ──► WGS 84 lon/lat ──► centroid picks the local UTM zone ──► measure in metres

Areas/lengths are never computed in degrees. One bad feature never fails the whole file:
every outcome is reported through ``Measurement.status``.
"""
from __future__ import annotations

import logging

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from app.core.geo import utm_epsg_for
from app.schemas.files import Measurement, MeasurementStatus
from app.services.crs import WGS84

logger = logging.getLogger(__name__)

_POLYGONAL = {"Polygon", "MultiPolygon"}
_LINEAR = {"LineString", "MultiLineString", "LinearRing"}
_POINTLIKE = {"Point", "MultiPoint"}


def _all_finite(geometry: BaseGeometry) -> bool:
    return bool(np.isfinite(shapely.get_coordinates(geometry)).all())


def _reproject(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    """Apply a pyproj Transformer to every vertex (vectorised, 2D)."""

    def apply(coords: np.ndarray) -> np.ndarray:  # coords has shape (N, 2)
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack((x, y))

    return shapely.transform(geometry, apply)


class MeasurementCalculator:
    """Create one per file/thread: it caches pyproj Transformers, which are not thread-safe."""

    def __init__(self, source_crs: CRS) -> None:
        self._to_wgs84: Transformer | None = (
            None if source_crs == WGS84 else Transformer.from_crs(source_crs, WGS84, always_xy=True)
        )
        self._to_utm: dict[int, Transformer] = {}

    def measure(self, geometry: BaseGeometry | None, problem: str | None = None) -> Measurement:
        if geometry is None:
            return Measurement(
                status=MeasurementStatus.UNSUPPORTED, message=problem or "Feature has no geometry"
            )
        gtype = geometry.geom_type
        if gtype in _POINTLIKE:
            return Measurement(
                status=MeasurementStatus.NOT_APPLICABLE, message=f"No measurement defined for {gtype}"
            )
        if gtype not in _POLYGONAL | _LINEAR:
            return Measurement(
                status=MeasurementStatus.UNSUPPORTED,
                message=f"Measurement is not supported for geometry type {gtype}",
            )

        try:
            return self._measure_supported(geometry, gtype)
        except Exception as exc:  # noqa: BLE001 - isolate failures to the single feature
            logger.warning("Measurement failed for %s: %s", gtype, exc)
            return Measurement(status=MeasurementStatus.ERROR, message=f"Measurement failed: {exc}")

    # ------------------------------------------------------------------
    def _measure_supported(self, geometry: BaseGeometry, gtype: str) -> Measurement:
        wgs84_geom = (
            geometry if self._to_wgs84 is None
            else _reproject(geometry, self._to_wgs84)
        )
        if not _all_finite(wgs84_geom):
            raise ValueError("coordinates fall outside the source CRS domain")
        _, miny, _, maxy = wgs84_geom.bounds
        if abs(miny) > 90 or abs(maxy) > 90:
            raise ValueError("latitude outside the valid range -90..90")

        centroid = wgs84_geom.centroid
        epsg = utm_epsg_for(centroid.x, centroid.y)
        projected = _reproject(wgs84_geom, self._utm_transformer(epsg))
        if not _all_finite(projected):
            raise ValueError("projection produced non-finite coordinates")
        crs_name = f"EPSG:{epsg}"

        if gtype in _POLYGONAL:
            message = None
            if not geometry.is_valid:
                message = (
                    f"Geometry is invalid ({explain_validity(geometry)}); "
                    "the result may be unreliable"
                )
            return Measurement(
                status=MeasurementStatus.MEASURED,
                area_sq_m=round(float(projected.area), 4),
                perimeter_m=round(float(projected.length), 4),
                projected_crs=crs_name,
                message=message,
            )
        return Measurement(
            status=MeasurementStatus.MEASURED,
            length_m=round(float(projected.length), 4),
            projected_crs=crs_name,
        )

    def _utm_transformer(self, epsg: int) -> Transformer:
        transformer = self._to_utm.get(epsg)
        if transformer is None:
            transformer = Transformer.from_crs(WGS84, CRS.from_epsg(epsg), always_xy=True)
            self._to_utm[epsg] = transformer
        return transformer