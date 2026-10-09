"""KML parser.

KML is always WGS 84 longitude/latitude (EPSG:4326) by specification, so the CRS is fixed.
Uses lxml with entity resolution and network access disabled (XXE / billion-laughs safe).
Namespaces are ignored (matched on local names) because KML 2.0/2.1/2.2 files differ.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from lxml import etree

from app.core.exceptions import InvalidFileError
from app.parsers.base import ParsedFile, RawFeature

KML_CRS = "EPSG:4326"
_SIMPLE_GEOMETRIES = {"Point", "LineString", "LinearRing", "Polygon"}
_ALL_GEOMETRIES = _SIMPLE_GEOMETRIES | {"MultiGeometry"}
_COMMA_SPACES = re.compile(r"\s*,\s*")  # tolerate the common "lon, lat, alt" mistake


# ---- tiny XML helpers -------------------------------------------------------------
def _local(el: Any) -> str | None:
    tag = el.tag
    return etree.QName(tag).localname if isinstance(tag, str) else None


def _child(el: Any, name: str) -> Any | None:
    for c in el:
        if _local(c) == name:
            return c
    return None


def _children(el: Any, name: str) -> list[Any]:
    return [c for c in el if _local(c) == name]


def _text(el: Any | None) -> str:
    return (el.text or "").strip() if el is not None else ""


# ---- geometry ---------------------------------------------------------------------
def _parse_coordinates(text: str, minimum: int) -> list[list[float]]:
    coords: list[list[float]] = []
    for token in _COMMA_SPACES.sub(",", text.strip()).split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ValueError(f"Invalid coordinate tuple: {token!r}")
        try:
            lon, lat = float(parts[0]), float(parts[1])  # altitude (3rd value) is ignored
        except ValueError:
            raise ValueError(f"Invalid coordinate tuple: {token!r}") from None
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError(f"Non-finite coordinate: {token!r}")
        coords.append([lon, lat])
    if len(coords) < minimum:
        raise ValueError(f"Expected at least {minimum} coordinates, found {len(coords)}")
    return coords


def _coordinates_of(el: Any) -> str:
    coords = _child(el, "coordinates")
    if coords is None:
        raise ValueError(f"<{_local(el)}> has no <coordinates>")
    return coords.text or ""


def _ring(boundary: Any) -> list[list[float]]:
    ring_el = _child(boundary, "LinearRing")
    if ring_el is None:
        raise ValueError("Polygon boundary has no <LinearRing>")
    ring = _parse_coordinates(_coordinates_of(ring_el), 3)
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    if len(ring) < 4:
        raise ValueError("Polygon ring needs at least 3 distinct vertices")
    return ring


def _simple_geometry(el: Any) -> dict[str, Any]:
    name = _local(el)
    if name == "Point":
        return {"type": "Point", "coordinates": _parse_coordinates(_coordinates_of(el), 1)[0]}
    if name in ("LineString", "LinearRing"):  # a stand-alone LinearRing is treated as a line
        return {"type": "LineString", "coordinates": _parse_coordinates(_coordinates_of(el), 2)}
    if name == "Polygon":
        outer = _child(el, "outerBoundaryIs")
        if outer is None:
            raise ValueError("Polygon has no <outerBoundaryIs>")
        rings = [_ring(outer)] + [_ring(inner) for inner in _children(el, "innerBoundaryIs")]
        return {"type": "Polygon", "coordinates": rings}
    raise ValueError(f"Unsupported geometry element <{name}>")


def _leaves(el: Any) -> list[dict[str, Any]]:
    """Flatten (possibly nested) MultiGeometry into simple geometries."""
    if _local(el) == "MultiGeometry":
        out: list[dict[str, Any]] = []
        for c in el:
            if _local(c) in _ALL_GEOMETRIES:
                out.extend(_leaves(c))
        return out
    return [_simple_geometry(el)]


def _combine(leaves: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not leaves:
        return None
    if len(leaves) == 1:
        return leaves[0]
    types = {g["type"] for g in leaves}
    if types == {"Point"}:
        return {"type": "MultiPoint", "coordinates": [g["coordinates"] for g in leaves]}
    if types == {"LineString"}:
        return {"type": "MultiLineString", "coordinates": [g["coordinates"] for g in leaves]}
    if types == {"Polygon"}:
        return {"type": "MultiPolygon", "coordinates": [g["coordinates"] for g in leaves]}
    return {"type": "GeometryCollection", "geometries": leaves}  # mixed: kept, not measured


# ---- attributes -------------------------------------------------------------------
def _properties(placemark: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for key in ("name", "description"):
        value = _text(_child(placemark, key))
        if value:
            props[key] = value
    extended = _child(placemark, "ExtendedData")
    if extended is not None:
        for el in extended.iter():
            kind = _local(el)
            key = el.get("name") if kind in ("Data", "SimpleData") else None
            if not key:
                continue
            if kind == "Data":
                value_el = _child(el, "value")
                props[key] = _text(value_el) if value_el is not None else _text(el)
            else:
                props[key] = _text(el)
    return props


# ---- parser -----------------------------------------------------------------------
class KMLParser:
    def parse(self, path: Path) -> ParsedFile:
        xml_parser = etree.XMLParser(
            resolve_entities=False, no_network=True, load_dtd=False,
            dtd_validation=False, huge_tree=False, remove_comments=True,
        )
        try:
            root = etree.parse(str(path), xml_parser).getroot()
        except etree.XMLSyntaxError as exc:
            raise InvalidFileError(f"File is not valid XML/KML: {exc}") from exc
        if root is None or _local(root) != "kml":
            raise InvalidFileError("Root element is not <kml>; this does not look like a KML file")

        features: list[RawFeature] = []
        warnings: list[str] = []
        placemark_no = 0
        for el in root.iter():
            if _local(el) != "Placemark":
                continue
            placemark_no += 1
            props = _properties(el)
            geometry_els = [c for c in el if _local(c) in _ALL_GEOMETRIES]
            if not geometry_els:
                label = props.get("name", "unnamed")
                warnings.append(
                    f"Placemark #{placemark_no} ({label}) has no supported geometry and was skipped"
                )
                continue
            try:
                leaves: list[dict[str, Any]] = []
                for g in geometry_els:
                    leaves.extend(_leaves(g))
                geometry = _combine(leaves)
                problem = None if geometry else "Placemark geometry is empty"
            except ValueError as exc:
                geometry, problem = None, str(exc)
            features.append(RawFeature(len(features), geometry, props, problem))

        if not features:
            raise InvalidFileError("KML contains no Placemarks with supported geometry")
        return ParsedFile(features=features, crs_definition=KML_CRS, warnings=warnings)
