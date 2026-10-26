import faiss
from progress import emit_progress, ProgressCallback
from manifest import update_stage
import numpy as np
from pathlib import Path
import os
import tempfile

from storage.sqlite import DB_PATH, get_conn

def save_index(index, path="indexes/docsassist.faiss"):
    index_path = Path(path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{index_path.name}.",
            suffix=".tmp",
            dir=index_path.parent,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        faiss.write_index(index, str(temp_path))
        os.replace(temp_path, index_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()

def load_index(path="indexes/docsassist.faiss"):
    return faiss.read_index(path)

def load_or_create_index(dimension, index_path="indexes/docsassist.faiss"):
    if Path(index_path).exists():
       return load_index(index_path)

    if dimension is None:
        return None

    base_index = faiss.IndexFlatIP(dimension)
    return faiss.IndexIDMap2(base_index)

def update_index(
    embeddings,
    chunk_ids,
    old_chunk_ids,
    doc_path,
    progress: ProgressCallback | None = None,
    db_path: str = DB_PATH,
):
    embeddings = np.asarray(embeddings, dtype=np.float32)
    chunk_ids = np.asarray(chunk_ids, dtype=np.int64)
    dimension = embeddings.shape[1] if embeddings.size > 0 else None

    update_stage(
        doc_path,
        stage = "indexing",
        status = "processing",
        current=0,
        total = len(chunk_ids)
    )

    emit_progress(
        progress,
        stage = "indexing",
        current = 0,
        total = len(chunk_ids),
        message = "Iniciando indexação"
    )
    
    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        valid_rows = conn.execute(
            f"""
            SELECT c.id
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id IN ({','.join('?' for _ in chunk_ids)})
              AND d.status IN ('processing', 'indexed')
            """,
            chunk_ids.tolist(),
        ).fetchall() if len(chunk_ids) else []
        valid_ids = {row["id"] for row in valid_rows}
        valid_mask = np.asarray(
            [int(chunk_id) in valid_ids for chunk_id in chunk_ids],
            dtype=bool,
        )
        active_chunk_ids = chunk_ids[valid_mask]
        active_embeddings = embeddings[valid_mask]
        index = load_or_create_index(dimension)

        if index is not None:
            if old_chunk_ids:
                old_ids = np.asarray(old_chunk_ids, dtype=np.int64)
                index.remove_ids(old_ids)
            if len(active_chunk_ids) > 0:
                index.add_with_ids(active_embeddings, active_chunk_ids)
            save_index(index)

    update_stage(
        doc_path,
        stage = "indexing",
        status = "done",
        current=len(active_chunk_ids),
        total = len(chunk_ids),
        vectors = len(active_chunk_ids),
        chunk_ids = active_chunk_ids.tolist(),
    )

    emit_progress(
        progress,
        stage = "indexing",
        current = len(active_chunk_ids),
        total = len(chunk_ids),
        message = "Indexação concluída",
        done = True
    )
    return True


def remove_chunk_ids(chunk_ids, index_path="indexes/docsassist.faiss", db_path=DB_PATH):
    ids = np.asarray(sorted({int(chunk_id) for chunk_id in chunk_ids}), dtype=np.int64)
    if ids.size == 0 or not Path(index_path).exists():
        return 0

    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        index = load_index(index_path)
        removed = int(index.remove_ids(ids))
        save_index(index, index_path)
    return removed
