import faiss
from progress import emit_progress, ProgressCallback
from manifest import update_stage, load_manifest
import numpy as np
from pathlib import Path

def save_index(index, path="indexes/docsassist.faiss"):
    faiss.write_index(index, path)

def load_index(path="indexes/docsassist.faiss"):
    return faiss.read_index(path)

def load_or_create_index(dimension, index_path="indexes/docsassist.faiss"):
    if Path(index_path).exists():
       return load_index(index_path)

    if dimension is None:
        return None

    base_index = faiss.IndexFlatIP(dimension)
    return faiss.IndexIDMap2(base_index)

def update_index(embeddings, chunk_ids, old_chunk_ids, doc_path, progress: ProgressCallback | None = None):
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
    
    index = load_or_create_index(dimension)

    if index is not None:

        if old_chunk_ids:
            old_ids = np.asarray(old_chunk_ids, dtype=np.int64)
            index.remove_ids(old_ids)
        if len(chunk_ids) > 0:
            index.add_with_ids(
                embeddings,
                chunk_ids
            )

        save_index(index)

    update_stage(
        doc_path,
        stage = "indexing",
        status = "done",
        current=len(chunk_ids),
        total = len(chunk_ids),
        vectors = len(chunk_ids),
        chunk_ids = chunk_ids.tolist(),
    )

    emit_progress(
        progress,
        stage = "indexing",
        current = len(chunk_ids),
        total = len(chunk_ids),
        message = "Indexação concluída",
        done = True
    )
    return True
