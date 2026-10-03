"""GET /files/{name}: download a file from the caller's own folder -- what
create_file made, a chart analyze_data drew, or something they uploaded.
Only the basename is honoured, so no path can reach another user's folder."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from harness.api.auth import get_current_user
from harness.tools.builtin.files import user_folder

router = APIRouter()

# shown in the page (an <img>); everything else downloads
INLINE = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TYPES = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
         ".md": "text/markdown; charset=utf-8", ".csv": "text/csv; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


KIND = {".pdf": "document", ".docx": "document", ".pptx": "slides", ".xlsx": "spreadsheet", ".csv": "spreadsheet",
        ".md": "text", ".txt": "text", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
        ".gif": "image", ".mp3": "audio", ".m4a": "audio", ".wav": "audio", ".webm": "audio", ".ogg": "audio"}


@router.get("/files")
async def list_files(user: dict = Depends(get_current_user)) -> list[dict]:
    """Everything in the user's folder, newest first: uploads, created files,
    charts, images and voice notes (the "My stuff" page)."""
    import asyncio

    def scan():
        folder = user_folder(user["user_id"])
        out = []
        for p in folder.iterdir():
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                out.append({"name": p.name, "size": st.st_size, "modified": st.st_mtime,
                            "kind": KIND.get(p.suffix.lower(), "file")})
        return sorted(out, key=lambda f: f["modified"], reverse=True)[:500]
    return await asyncio.to_thread(scan)


@router.get("/files/{name}")
async def download(name: str, user: dict = Depends(get_current_user)):
    safe = Path(name).name
    if not safe or safe != name or safe.startswith("."):
        raise HTTPException(status_code=404, detail="No such file.")
    path = user_folder(user["user_id"]) / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No such file.")
    ext = path.suffix.lower()
    media = TYPES.get(ext) or mimetypes.guess_type(safe)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, filename=safe,
                        content_disposition_type="inline" if ext in INLINE else "attachment",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
