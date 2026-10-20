import faiss
from progress import emit_progress, ProgressCallback
from manifest import update_stage
import numpy as np


def save_index(index, path="indexes/docsassist.faiss"):
    faiss.write_index(index, path)

def load_index(path="indexes/docsassist.faiss"):
    return faiss.read_index(path)

def build_index(embeddings, chunk_ids, doc_path, progress: ProgressCallback | None = None):
    embeddings = np.asarray(embeddings, dtype=np.float32)
    chunk_ids = np.asarray(chunk_ids, dtype=np.int64)
    dimesion = embeddings.shape[1]

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
    
    base_index = faiss.IndexFlatIP(dimesion)
    index = faiss.IndexIDMap2(base_index)
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
        vectors = len(chunk_ids)
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
