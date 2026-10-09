"""Small pure-Python geographic helpers (no third-party dependencies)."""
from __future__ import annotations

UPS_NORTH_EPSG = 32661  # WGS 84 / UPS North (N,E)
UPS_SOUTH_EPSG = 32761  # WGS 84 / UPS South (N,E)


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG code of the WGS 84 UTM zone containing the point.

    UTM only covers 80°S–84°N, so the polar caps fall back to UPS.
    Longitudes are normalised, so 0–360 style data works too.
    """
    if lat >= 84.0:
        return UPS_NORTH_EPSG
    if lat <= -80.0:
        return UPS_SOUTH_EPSG
    lon = (lon + 180.0) % 360.0 - 180.0
    zone = int((lon + 180.0) // 6) + 1  # 1..60
    return (32600 if lat >= 0 else 32700) + zone


def looks_like_lonlat(bounds: tuple[float, float, float, float]) -> bool:
    """True if (minx, miny, maxx, maxy) fits inside valid longitude/latitude ranges."""
    minx, miny, maxx, maxy = bounds
    return -180.0 <= minx <= maxx <= 180.0 and -90.0 <= miny <= maxy <= 90.0
