from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.routes.files import router as files_router
from app.config import get_settings
from app.core.exceptions import AppError

_DESCRIPTION = """
Upload a **Shapefile (.zip)** or **KML** file and get back its features and accurate
**area / length measurements** (in metres, computed in a local UTM projection - never in degrees).
"""


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", description=_DESCRIPTION)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code, **exc.extra},
        )

    @app.middleware("http")
    async def reject_oversized_uploads(request: Request, call_next):
        # Cheap early rejection based on Content-Length (the service enforces the exact limit).
        length = request.headers.get("content-length", "")
        if request.method == "POST" and length.isdigit():
            if int(length) > settings.max_upload_bytes + 1024 * 1024:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"File exceeds the {settings.max_upload_mb} MB upload limit",
                        "code": "file_too_large",
                    },
                )
        return await call_next(request)

    app.include_router(files_router)

    @app.get("/health", tags=["health"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
