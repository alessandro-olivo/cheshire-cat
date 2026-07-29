import os
import aiofiles
import mimetypes
from uuid import uuid5, NAMESPACE_URL
from typing import List
from pydantic import BaseModel

from fastapi import UploadFile, File, Path
from fastapi import HTTPException
from fastapi.responses import FileResponse

from urllib.parse import urljoin

from cat import config, endpoint, user, execute_hook


class UploadedFile(BaseModel):
    path: str
    url: str
    mime_type: str

class UploadedFileResponse(BaseModel):
    url: str
    mime_type: str


@endpoint.post("/uploads", tags=["Uploads"], role="authenticated")
async def upload_file(
    file: UploadFile = File(...),
) -> UploadedFileResponse:
    hashed_user_id = str(uuid5(NAMESPACE_URL, str(user.id)))
    save_dir = os.path.join(config.UPLOADS_PATH, hashed_user_id)
    os.makedirs(save_dir, exist_ok=True)

    safe_filename = os.path.basename(file.filename)
    file_location = os.path.join(save_dir, safe_filename)

    async with aiofiles.open(file_location, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            await buffer.write(chunk)

    mime_type, _ = mimetypes.guess_type(safe_filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    url = urljoin(config.URL, f"uploads/{hashed_user_id}/{safe_filename}")

    await execute_hook(
        "after_file_upload",
        UploadedFile(
            path=file_location,
            url=url,
            mime_type=mime_type
        ),
    )

    return UploadedFileResponse(
        url=url,
        mime_type=mime_type
    )


@endpoint.get("/uploads", tags=["Uploads"], role="authenticated")
async def get_uploaded_files() -> List[UploadedFileResponse]:
    """Retrieve list of uploaded file URLs uploaded by a specific user."""

    hashed_user_id = str(uuid5(NAMESPACE_URL, str(user.id)))
    user_dir = os.path.join(config.UPLOADS_PATH, hashed_user_id)

    uploads = []
    # every file under the user's folder, at any depth. os.walk rather than a
    # glob: `**.*` skipped both dotfiles and extensionless files.
    for folder, _, filenames in os.walk(user_dir):
        for filename in sorted(filenames):
            path = os.path.join(folder, filename)
            relative = os.path.relpath(path, config.UPLOADS_PATH)
            uploads.append(
                UploadedFileResponse(
                    url=urljoin(config.URL, f"uploads/{relative}"),
                    mime_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                )
            )
    return uploads


@endpoint.get("/uploads/{path:path}", tags=["Uploads"])
async def get_uploaded_file(
    path: str = Path(...),
) -> FileResponse:
    uploads_root = os.path.abspath(config.UPLOADS_PATH)
    full_path = os.path.abspath(os.path.join(uploads_root, path))

    # `path` is user input: `..` segments would otherwise escape the uploads root
    if not full_path.startswith(uploads_root + os.sep):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden"
        )

    if os.path.isfile(full_path):
        return FileResponse(full_path)
    else:
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )
