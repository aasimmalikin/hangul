"""POST /upload — embed a document into the caller's rows in pgvector."""
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from harness.api.session import get_session_id
from harness.api.auth import get_current_user
from harness.retrieval.upload_ingest import extract_text, chunk_text, UploadError, MAX_BYTES
from harness.security.detector import scan
from harness.policy.audit import AuditLog

_audit = AuditLog()   # same data/audit.jsonl as ask.py; a separate handle avoids the circular import
from harness.retrieval import pg_store
from harness.retrieval.embeddings import get_embedder

router = APIRouter()
_SESSIONS_ROOT  = Path("data/sessions")
# One embeddings request per 64 chunks rather than one per chunk.
EMBED_BATCH = 64

def _safe_session_dir(user_id: str)->Path:
    """Return and create this session's folder guarding against path tricks."""
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
    d = _SESSIONS_ROOT/safe
    d.mkdir(parents = True, exist_ok = True)
    return d

@router.post("/upload")
async def upload(file:UploadFile = File(...), user: dict = Depends(get_current_user)):
    data = b""
    while chunk:= await file.read(1024*1024):
        data+=chunk
        if len(data)>MAX_BYTES:
            raise HTTPException(status_code = 413, detail = "File too large")
    
    filename = file.filename or "upload"

    try:
        text = extract_text(file.filename or "upload", data)
    except UploadError as e:
        raise HTTPException(status_code = 400, detail = str(e))
    
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code = 400, detail = "No readable text found in the file")
    
    # Scan at ingest: a document carrying instructions for the assistant is
    # indexed anyway (the model sees it spotlighted as untrusted data), but the
    # person is told now, before it is ever retrieved.
    suspicious = [i for i, ch in enumerate(chunks) if scan(ch).score >= 0.45]
    whole = scan(text)
    if suspicious or whole.hidden_chars >= 8:
        _audit.record_security(layer="upload", severity=whole.severity if whole.severity != "none" else "medium",
                               source=file.filename or "upload", action="flagged", user_id=user["user_id"],
                               reasons=whole.reasons[:4] or [f"{len(suspicious)} suspicious chunk(s)"],
                               suspicious_chunks=len(suspicious))

    # Embedded in batches and written to pgvector in one transaction, keyed by
    # the caller's subject: the upload outlives this worker and is reachable
    # from any replica, and re-uploading the same file name replaces it rather
    # than indexing it twice.
    embedder = get_embedder()
    embedded: list[tuple[str, list[float]]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        embedded.extend(zip(batch, await embedder.embed_many(batch), strict = True))

    await pg_store.add_chunks(
        embedded,
        user_id = user["user_id"],
        source = filename,
        embed_model = embedder.model,
    )
    
    safe_name = Path(filename).name
    session_dir = _safe_session_dir(user["user_id"])
    (session_dir/safe_name).write_bytes(data)
    
    return {
        "session_id": user["user_id"],
        "filename": file.filename,
        "chunks_indexed": len(chunks),
        "mcp_path": f"{session_dir.name}/{safe_name}",
        "message": f"Indexed {len(chunks)} chunks from {file.filename}",
        "security": {
            "suspicious_chunks": len(suspicious), "hidden_chars": whole.hidden_chars,
            "warning": (f"{len(suspicious)} passage(s) in this file read like instructions to the assistant. "
                        "They will be treated as data, not followed.") if suspicious else None,
        },
    }