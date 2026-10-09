from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.deps import get_file_service
from app.schemas.files import FeaturesResponse, FileInfo, MeasurementsResponse
from app.services.file_service import FileService

router = APIRouter(prefix="/api/files", tags=["files"])

_ERRORS = {
    404: {"description": "File not found"},
    409: {"description": "File exists but processing failed"},
}
_Limit = Query(default=100, ge=1, le=1000, description="Page size")
_Offset = Query(default=0, ge=0, description="Number of features to skip")


@router.post(
    "/",
    response_model=FileInfo,
    status_code=201,
    summary="Upload a Shapefile (.zip) or KML file",
    responses={
        413: {"description": "File too large"},
        415: {"description": "Unsupported file type"},
        422: {"description": "File content could not be processed (body includes file_id)"},
    },
)
def upload_file(
    file: UploadFile = File(..., description="A .zip containing a Shapefile, or a .kml file"),
    service: FileService = Depends(get_file_service),
) -> FileInfo:
    # Plain `def` on purpose: parsing/projection is CPU-bound, so FastAPI runs it in a
    # worker thread instead of blocking the event loop.
    return service.ingest(file.filename, file.file).to_info()


@router.get("/{file_id}/", response_model=FileInfo, summary="File information",
            responses={404: _ERRORS[404]})
def get_file(file_id: str, service: FileService = Depends(get_file_service)) -> FileInfo:
    return service.get_info(file_id).to_info()


@router.get("/{file_id}/features/", response_model=FeaturesResponse,
            summary="Extracted features (geometry, CRS, properties)", responses=_ERRORS)
def get_features(
    file_id: str,
    limit: int = _Limit,
    offset: int = _Offset,
    service: FileService = Depends(get_file_service),
) -> FeaturesResponse:
    return service.list_features(file_id, limit, offset)


@router.get("/{file_id}/measurements/", response_model=MeasurementsResponse,
            summary="Per-feature measurements plus a summary", responses=_ERRORS)
def get_measurements(
    file_id: str,
    limit: int = _Limit,
    offset: int = _Offset,
    service: FileService = Depends(get_file_service),
) -> MeasurementsResponse:
    return service.get_measurements(file_id, limit, offset)
