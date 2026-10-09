"""Pydantic models: used for the API contract and for the persisted record."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FileType(str, Enum):
    SHAPEFILE = "shapefile"
    KML = "kml"


class MeasurementStatus(str, Enum):
    MEASURED = "MEASURED"                # area/length calculated
    NOT_APPLICABLE = "NOT_APPLICABLE"    # e.g. Point: nothing to measure
    UNSUPPORTED = "UNSUPPORTED"          # null geometry, GeometryCollection, ...
    ERROR = "ERROR"                      # transformation or calculation failed


class Measurement(BaseModel):
    status: MeasurementStatus
    area_sq_m: float | None = None       # Polygon / MultiPolygon
    perimeter_m: float | None = None     # Polygon / MultiPolygon
    length_m: float | None = None        # LineString / MultiLineString
    projected_crs: str | None = None     # CRS the measurement was computed in
    message: str | None = None           # why something was skipped / caveats


class Feature(BaseModel):
    feature_id: int
    geometry_type: str | None
    geometry: dict[str, Any] | None      # GeoJSON, in the file's own CRS
    crs: str
    properties: dict[str, Any] = Field(default_factory=dict)
    measurement: Measurement


class FileInfo(BaseModel):
    id: str
    filename: str
    file_type: FileType
    status: FileStatus
    feature_count: int
    crs: str | None = None
    crs_assumed: bool = False
    created_at: datetime
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class FileRecord(FileInfo):
    """What is persisted: file info plus every extracted feature."""

    features: list[Feature] = Field(default_factory=list)

    def to_info(self) -> FileInfo:
        return FileInfo.model_validate(self.model_dump(exclude={"features"}))


class FeaturesResponse(BaseModel):
    file_id: str
    crs: str | None
    total: int
    limit: int
    offset: int
    features: list[Feature]


class FeatureMeasurement(BaseModel):
    feature_id: int
    geometry_type: str | None
    crs: str
    measurement: Measurement


class MeasurementSummary(BaseModel):
    status_counts: dict[str, int]
    total_area_sq_m: float
    total_length_m: float


class MeasurementsResponse(BaseModel):
    file_id: str
    crs: str | None
    total: int
    limit: int
    offset: int
    summary: MeasurementSummary          # computed over ALL features, not just this page
    measurements: list[FeatureMeasurement]
