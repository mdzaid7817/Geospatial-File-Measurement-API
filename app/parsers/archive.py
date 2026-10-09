"""Safe extraction of a Shapefile from an uploaded ZIP. Stdlib only.

Safety properties:
  * archive member names are never used as output paths (we write to fixed names),
    so path traversal ("../../x") is impossible;
  * entry count and *actual* decompressed bytes are capped (zip-bomb guard);
  * only the shapefile components we need are ever read.
"""
from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

from app.core.exceptions import InvalidFileError

REQUIRED = (".shp", ".shx", ".dbf")
OPTIONAL = (".prj", ".cpg")
_CHUNK = 1024 * 1024


def extract_shapefile(
    zip_path: Path, dest_dir: Path, *, max_entries: int, max_uncompressed_bytes: int
) -> tuple[Path, list[str]]:
    """Extract one shapefile to ``dest_dir/layer.*``; return (path to layer.shp, warnings)."""
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if len(infos) > max_entries:
                raise InvalidFileError(f"Archive has too many files (limit is {max_entries})")

            # Group components by (directory, stem), case-insensitively.
            groups: dict[tuple[str, str], dict[str, zipfile.ZipInfo]] = {}
            for info in infos:
                name = PurePosixPath(info.filename.replace("\\", "/"))
                if name.name.startswith(".") or "__MACOSX" in name.parts:
                    continue
                ext = name.suffix.lower()
                if ext in REQUIRED + OPTIONAL:
                    groups.setdefault((str(name.parent).lower(), name.stem.lower()), {})[ext] = info

            with_shp = {k: v for k, v in groups.items() if ".shp" in v}
            if not with_shp:
                raise InvalidFileError("ZIP archive does not contain a .shp file")
            complete = sorted(k for k, v in with_shp.items() if all(e in v for e in REQUIRED))
            if not complete:
                key = sorted(with_shp)[0]
                missing = ", ".join(e for e in REQUIRED if e not in with_shp[key])
                raise InvalidFileError(
                    f"Shapefile '{key[1]}' is missing required component(s): {missing}"
                )
            chosen = complete[0]
            if len(with_shp) > 1:
                warnings.append(
                    f"Archive contains {len(with_shp)} shapefiles; only '{chosen[1]}' was processed"
                )

            parts = groups[chosen]
            if sum(i.file_size for i in parts.values()) > max_uncompressed_bytes:
                raise InvalidFileError("Shapefile exceeds the maximum uncompressed size")

            written = 0
            for ext, info in parts.items():
                with zf.open(info) as src, open(dest_dir / f"layer{ext}", "wb") as dst:
                    while chunk := src.read(_CHUNK):
                        written += len(chunk)
                        if written > max_uncompressed_bytes:  # header sizes can lie
                            raise InvalidFileError("Shapefile exceeds the maximum uncompressed size")
                        dst.write(chunk)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        # RuntimeError: encrypted entries; NotImplementedError: unsupported compression
        raise InvalidFileError(f"Cannot read ZIP archive: {exc}") from exc

    return dest_dir / "layer.shp", warnings
