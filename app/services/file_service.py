"""Orchestrates the whole flow: validate → save → parse → CRS → measure → persist."""
from __future__ import annotations

import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from pyproj import CRS
from pyproj.exceptions import ProjError
from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.config import Settings
from app.core.exceptions import (
    FileProcessingFailedError,
    FileTooLargeError,
    InvalidFileError,
    RecordNotFoundError,
    UnsupportedFileTypeError,
)
from app.core.geo import looks_like_lonlat
from app.core.serialization import to_jsonable
from app.parsers.base import FileParser, ParsedFile, RawFeature
from app.parsers.kml_parser import KMLParser
from app.parsers.shapefile_parser import ShapefileParser
from app.schemas.files import (
    FeatureMeasurement,
    FeaturesResponse,
    Feature,
    FileRecord,
    FileStatus,
    FileType,
    MeasurementsResponse,
    MeasurementStatus,
    MeasurementSummary,
)
from app.services.crs import WGS84, crs_label, resolve_crs
from app.services.measurement import MeasurementCalculator
from app.services.storage import JsonFileRepository

_CHUNK = 1024 * 1024
_GEOMETRY_ERRORS = (ValueError, TypeError, KeyError, IndexError, ShapelyError)


class FileService:
    def __init__(self, repository: JsonFileRepository, settings: Settings) -> None:
        self._repo = repository
        self._settings = settings
        self._parsers: dict[str, tuple[FileType, FileParser]] = {
            ".kml": (FileType.KML, KMLParser()),
            ".zip": (
                FileType.SHAPEFILE,
                ShapefileParser(settings.max_zip_entries, settings.max_uncompressed_bytes),
            ),
        }

    # ------------------------------------------------------------------ upload
    def ingest(self, filename: str | None, stream: BinaryIO) -> FileRecord:
        display_name = PurePosixPath((filename or "").replace("\\", "/")).name
        suffix = PurePosixPath(display_name).suffix.lower()
        if suffix not in self._parsers:
            raise UnsupportedFileTypeError(
                f"Unsupported file type '{suffix or display_name or 'unknown'}'. "
                "Upload a .zip (containing a Shapefile) or a .kml file."
            )
        file_type, parser = self._parsers[suffix]
        file_id = uuid.uuid4().hex

        with tempfile.TemporaryDirectory(prefix="geo_") as tmp:
            upload_path = Path(tmp) / f"upload{suffix}"
            try:
                self._save_stream(stream, upload_path)
                parsed = parser.parse(upload_path)
                record = self._build_record(file_id, display_name, file_type, parsed)
            except InvalidFileError as exc:
                # Keep a FAILED record so GET /api/files/{id}/ can explain what went wrong.
                self._repo.save(
                    FileRecord(
                        id=file_id, filename=display_name, file_type=file_type,
                        status=FileStatus.FAILED, error=exc.message, feature_count=0,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                exc.extra["file_id"] = file_id
                raise

        self._repo.save(record)
        return record

    def _save_stream(self, stream: BinaryIO, dest: Path) -> None:
        limit = self._settings.max_upload_bytes
        written = 0
        with open(dest, "wb") as out:
            while chunk := stream.read(_CHUNK):
                written += len(chunk)
                if written > limit:
                    raise FileTooLargeError(
                        f"File exceeds the {self._settings.max_upload_mb} MB upload limit"
                    )
                out.write(chunk)
        if written == 0:
            raise InvalidFileError("Uploaded file is empty")

    # ----------------------------------------------------------------- process
    def _build_record(
        self, file_id: str, filename: str, file_type: FileType, parsed: ParsedFile
    ) -> FileRecord:
        shapes: list[tuple[RawFeature, BaseGeometry | None, str | None]] = [
            (raw, *self._to_shapely(raw)) for raw in parsed.features
        ]
        warnings = list(parsed.warnings)

        crs, assumed = self._determine_crs(parsed.crs_definition, [g for _, g, _ in shapes if g])
        if assumed:
            warnings.append(
                "No CRS information found; assumed EPSG:4326 because all coordinates "
                "are valid longitude/latitude values"
            )
        label = crs_label(crs)
        try:
            calculator = MeasurementCalculator(crs)
        except (ProjError, ValueError) as exc:
            raise InvalidFileError(f"Cannot transform from CRS '{label}' to WGS 84: {exc}") from exc

        features = [
            Feature(
                feature_id=raw.index,
                geometry_type=geom.geom_type if geom is not None else None,
                geometry=raw.geometry if geom is not None else None,
                crs=label,
                properties=to_jsonable(raw.properties),
                measurement=calculator.measure(geom, problem),
            )
            for raw, geom, problem in shapes
        ]
        return FileRecord(
            id=file_id, filename=filename, file_type=file_type, status=FileStatus.COMPLETED,
            feature_count=len(features), crs=label, crs_assumed=assumed,
            created_at=datetime.now(timezone.utc), warnings=warnings, features=features,
        )

    @staticmethod
    def _to_shapely(raw: RawFeature) -> tuple[BaseGeometry | None, str | None]:
        if raw.geometry is None:
            return None, raw.problem
        try:
            geom = shape(raw.geometry)
        except _GEOMETRY_ERRORS as exc:
            return None, f"Invalid geometry: {exc}"
        if geom.is_empty:
            return None, "Geometry is empty"
        return geom, raw.problem

    @staticmethod
    def _determine_crs(definition: str | None, geoms: list[BaseGeometry]) -> tuple[CRS, bool]:
        """Return (crs, assumed). If the file has no CRS, accept lon/lat-looking data as WGS 84."""
        if definition:
            return resolve_crs(definition), False
        if not geoms:
            raise InvalidFileError("File has no usable geometry and no CRS information")
        bounds = [g.bounds for g in geoms]
        overall = (
            min(b[0] for b in bounds), min(b[1] for b in bounds),
            max(b[2] for b in bounds), max(b[3] for b in bounds),
        )
        if looks_like_lonlat(overall):
            return WGS84, True
        raise InvalidFileError(
            "File has no CRS (.prj missing) and its coordinates are not valid longitude/latitude, "
            "so the coordinate system cannot be determined"
        )

    # ------------------------------------------------------------------- reads
    def get_info(self, file_id: str) -> FileRecord:
        record = self._repo.get(file_id)
        if record is None:
            raise RecordNotFoundError(f"File '{file_id}' not found")
        return record

    def _get_completed(self, file_id: str) -> FileRecord:
        record = self.get_info(file_id)
        if record.status != FileStatus.COMPLETED:
            raise FileProcessingFailedError(
                f"File '{file_id}' failed processing: {record.error or 'unknown error'}"
            )
        return record

    def list_features(self, file_id: str, limit: int, offset: int) -> FeaturesResponse:
        record = self._get_completed(file_id)
        return FeaturesResponse(
            file_id=record.id, crs=record.crs, total=len(record.features),
            limit=limit, offset=offset, features=record.features[offset : offset + limit],
        )

    def get_measurements(self, file_id: str, limit: int, offset: int) -> MeasurementsResponse:
        record = self._get_completed(file_id)
        counts = Counter(f.measurement.status for f in record.features)
        summary = MeasurementSummary(
            status_counts={s.value: counts.get(s, 0) for s in MeasurementStatus},
            total_area_sq_m=round(sum(f.measurement.area_sq_m or 0.0 for f in record.features), 4),
            total_length_m=round(sum(f.measurement.length_m or 0.0 for f in record.features), 4),
        )
        page = record.features[offset : offset + limit]
        return MeasurementsResponse(
            file_id=record.id, crs=record.crs, total=len(record.features),
            limit=limit, offset=offset, summary=summary,
            measurements=[
                FeatureMeasurement(
                    feature_id=f.feature_id, geometry_type=f.geometry_type,
                    crs=f.crs, measurement=f.measurement,
                )
                for f in page
            ],
        )
