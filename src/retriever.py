import numpy as np

from storage.sqlite import get_chunks_by_ids
from src.embedder import generate_query_embedding
from src.indexer import load_index

def retrieve(query, index_path="indexes/docsassist.faiss", k=3):
    index = load_index(index_path)

    if index.ntotal == 0:
        return []
    
    effective_k = min(k, index.ntotal)
    
    query_embedding = generate_query_embedding(query)
    query_embedding = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)

    scores, ids = index.search(query_embedding, effective_k)    

    results = []

    for chunk_id, score in zip(ids[0], scores[0]):
        chunk_id = int(chunk_id)
        score = float(score)

        chunk = get_chunks_by_ids([chunk_id])[0]

        results.append({
            'chunk_id': chunk['id'],
            'score': score,
            'text': chunk['content'],
            'section': chunk['section'],
            'page_start': chunk['page_start'],
            'page_end': chunk['page_end'],
        })

    return results
