import faiss
import numpy as np

def save_index(index, path="indexes/docsassist.faiss"):
    faiss.write_index(index, path)

def load_index(path="indexes/docsassist.faiss"):
    return faiss.read_index(path)

def build_index(embeddings, chunk_ids):
    embeddings = np.asarray(embeddings, dtype=np.float32)
    chunk_ids = np.asarray(chunk_ids, dtype=np.int64)
    dimesion = embeddings.shape[1]
    base_index = faiss.IndexFlatIP(dimesion)
    index = faiss.IndexIDMap2(base_index)
    index.add_with_ids(
        embeddings,
        chunk_ids
    )
    save_index(index)
