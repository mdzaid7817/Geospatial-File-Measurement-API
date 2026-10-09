"""CRS helpers built on pyproj."""
from __future__ import annotations

from pyproj import CRS
from pyproj.exceptions import CRSError

from app.core.exceptions import InvalidFileError

WGS84 = CRS.from_epsg(4326)


def resolve_crs(definition: str) -> CRS:
    """Parse an 'EPSG:xxxx' string or a .prj WKT into a pyproj CRS."""
    try:
        return CRS.from_user_input(definition)
    except CRSError as exc:
        raise InvalidFileError(f"Unrecognised coordinate reference system: {exc}") from exc


def crs_label(crs: CRS) -> str:
    """Short human label such as 'EPSG:4326'; falls back to the CRS name."""
    authority = crs.to_authority(min_confidence=70)
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name or "UNKNOWN"
