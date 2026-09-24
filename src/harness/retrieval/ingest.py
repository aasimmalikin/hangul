"""Read text files -> chunk -> embed -> load the shared corpus into pgvector.

Writes rows with ``user_id IS NULL`` in ``document_chunks``; the swap is one
transaction, so a search running during a re-ingest sees the old corpus or the
new one, never a half-filled table. ``--backend json`` keeps the old data/index.json
behaviour for a machine with no database (evals on a laptop, mostly).
"""

import argparse
import asyncio
import hashlib
from pathlib import Path

from harness.retrieval import pg_store
from harness.retrieval.chunking import chunk_text
from harness.retrieval.embeddings import get_embedder
from harness.retrieval.index_version import index_version
from harness.retrieval.store import VectorStore

CHUNK_SIZE = 120
OVERLAP = 20
# Embeddings are the slow part and the API takes batches; 64 keeps a single
# request well under the token ceiling while cutting round trips ~64x.
BATCH = 64


async def ingest(doc_dir: str, index_path: str = "data/index.json", *, backend: str = "pgvector") -> None:
    embedder = get_embedder()
    files = sorted(Path(doc_dir).glob("*.txt"))
    corpus = "".join(f.read_text() for f in files)
    corpus_hash = hashlib.sha256(corpus.encode()).hexdigest()[:12]
    ver = index_version(
        chunk_size=CHUNK_SIZE, overlap=OVERLAP, embed_model=embedder.model, corpus_hash=corpus_hash
    )

    pending: list[tuple[str, str]] = [
        (f.name, chunk)
        for f in files
        for chunk in chunk_text(f.read_text(), chunk_size=CHUNK_SIZE, overlap=OVERLAP)
    ]

    rows: list[tuple[str, str, list[float]]] = []
    for start in range(0, len(pending), BATCH):
        batch = pending[start : start + BATCH]
        vectors = await embedder.embed_many([text for _source, text in batch])
        rows.extend((source, text, vec) for (source, text), vec in zip(batch, vectors, strict=True))

    if backend == "pgvector":
        n = await asyncio.to_thread(
            pg_store.replace_corpus_sync, rows, embed_model=embedder.model, index_version=ver
        )
        target = "postgres:document_chunks (user_id IS NULL)"
    else:
        store = VectorStore(Path(index_path))
        for source, text, vec in rows:
            store.add(text=text, source=source, embedding=vec)
        store.save()
        n, target = len(rows), index_path

    print(f"ingested {n} chunks from {len(files)} files -> {target}")
    print(f"index_version: {ver}")

    Path("data/index_version.txt").write_text(ver)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doc_dir", nargs="?", default="docs")
    parser.add_argument(
        "--backend", choices=["pgvector", "json"], default="pgvector",
        help="where to write the corpus (default: pgvector)",
    )
    parser.add_argument("--index-path", default="data/index.json", help="only used with --backend json")
    args = parser.parse_args()
    asyncio.run(ingest(args.doc_dir, args.index_path, backend=args.backend))


if __name__ == "__main__":
    main()
