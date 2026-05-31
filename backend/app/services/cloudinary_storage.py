from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool


def cloudinary_configured() -> bool:
    if os.getenv("DEEPPAPER_DISABLE_EXTERNAL") == "1":
        return False
    return all(
        os.getenv(name)
        for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
    )


async def upload_paper_asset(file_bytes: bytes, filename: str, content_type: str | None = None) -> dict[str, Any] | None:
    if not cloudinary_configured():
        return None
    try:
        return await run_in_threadpool(_upload_paper_asset_sync, file_bytes, filename, content_type)
    except Exception as exc:
        return {"stored": False, "error": str(exc), "folder": os.getenv("CLOUDINARY_UPLOAD_FOLDER", "researchai/papers")}


def _upload_paper_asset_sync(file_bytes: bytes, filename: str, content_type: str | None = None) -> dict[str, Any]:
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    folder = os.getenv("CLOUDINARY_UPLOAD_FOLDER", "researchai/papers").strip("/") or "researchai/papers"
    suffix = Path(filename or "paper.pdf").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix) as temp_file:
        temp_file.write(file_bytes)
        temp_file.flush()
        result = cloudinary.uploader.upload(
            temp_file.name,
            resource_type="raw",
            folder=folder,
            use_filename=True,
            unique_filename=True,
            overwrite=False,
            tags=["researchai", "paper"],
            context={"original_filename": filename or "paper", "content_type": content_type or "application/octet-stream"},
        )

    return {
        "stored": True,
        "public_id": result.get("public_id"),
        "secure_url": result.get("secure_url"),
        "resource_type": result.get("resource_type"),
        "bytes": result.get("bytes"),
        "format": result.get("format"),
        "folder": folder,
    }
