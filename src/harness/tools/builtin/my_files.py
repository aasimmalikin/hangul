"""my_files: list and read the files in the user's own folder.

One tool with an ``action`` argument instead of the fourteen MCP filesystem
tools, because every tool's schema is sent on every model call. Writing is
``create_file`` (a new file, never an overwrite); images are ``view_image``.

Only the basename of ``name`` is honoured, so the model cannot point it
outside ``data/sessions/<user>`` -- the same forcing as ``view_image``.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from harness.media.vision import IMAGE_TYPES
from harness.retrieval.upload_ingest import TEXT_TYPES, UploadError, extract_text
from harness.tools.base import Tool

SESSIONS = Path("data/sessions")
MAX_CHARS = 15_000
LIST_LIMIT = 100


def _folder(user_id: str) -> Path:
    return SESSIONS / "".join(c for c in user_id if c.isalnum() or c in "-_")


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 ** 2 else f"{n / 1024 ** 2:.1f} MB"


def _list(folder: Path) -> str:
    files = sorted((p for p in folder.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "The user's folder is empty."
    lines = []
    for p in files[:LIST_LIMIT]:
        st = p.stat()
        when = datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%d")
        lines.append(f"- {p.name} ({_size(st.st_size)}, {when})")
    more = f"\n…and {len(files) - LIST_LIMIT} more." if len(files) > LIST_LIMIT else ""
    return f"{len(files)} file(s), newest first:\n" + "\n".join(lines) + more


def _read(folder: Path, name: str) -> str:
    path = folder / Path(name).name
    if not path.is_file():
        return f"No file named {Path(name).name!r}. Call my_files with action='list' to see the exact names."
    ext = path.suffix.lower()
    if ext in IMAGE_TYPES:
        return f"{path.name} is an image; use view_image to look at it."
    if ext not in TEXT_TYPES:
        return f"{path.name} is not a document this tool can read (readable: {', '.join(sorted(TEXT_TYPES))})."
    try:
        text = extract_text(path.name, path.read_bytes())
    except UploadError as e:
        return f"Could not read {path.name}: {e}"
    text = text.strip() or "(the file has no readable text)"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n…[truncated at {MAX_CHARS} characters; use search_docs for a specific part]"
    return f"[{path.name}]\n{text}"


def make_my_files_tool(user_id: str) -> Tool:
    async def my_files(action: str = "list", name: str = "") -> str:
        folder = _folder(user_id)
        if not folder.is_dir():
            return "The user's folder is empty."
        if action == "read":
            if not name:
                return "Pass the file name to read, e.g. name='notes.txt'."
            return await asyncio.to_thread(_read, folder, name)
        return await asyncio.to_thread(_list, folder)

    return Tool(
        name="my_files",
        description=(
            "The files in the user's own folder: what they uploaded and files made for them. "
            "action='list' shows the names; action='read' with name='notes.txt' returns a document's full text "
            "(txt, md, csv, pdf, docx, xlsx). To find something inside documents, prefer search_docs; "
            "to make a file, use create_file; for images, use view_image."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "read"]},
                "name": {"type": "string", "description": "Exact file name, for action='read'."},
            },
            "required": ["action"],
        },
        handler=my_files,
    )
