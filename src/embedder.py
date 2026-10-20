import json
import requests
import numpy as np

from manifest import update_stage
from storage.sqlite import get_document_by_path, get_chunks_by_document
from progress import ProgressCallback, emit_progress

EMBEDDER_URL = "http://embedder:8001/embed"
EMBED_BATCH_SIZE = 64

def count_tokens(texts: list[str]) -> list[str]:
    response = requests.post(
        "http://embedder:8001/token-count",
        json={'texts': texts },
    )

    response.raise_for_status()

    return response.json()['token_counts']

def embed(doc_path, progress: ProgressCallback | None = None):
    doc = get_document_by_path(str(doc_path))
    chunks = get_chunks_by_document(doc['id'])

    total_chunks = len(chunks)
    
    update_stage(
        doc_path,
        stage = "embedding",
        status = "processing",
        current = 0,
        total = total_chunks
    )

    all_embeddings = []
    all_chunks_ids = []

    for start in range(0, total_chunks, EMBED_BATCH_SIZE):
        texts = []
        chunk_ids = []
        batch = chunks[start:start + EMBED_BATCH_SIZE]
    
        for chunk in batch:
            chunk_ids.append(chunk['id'])
            texts.append("passage: " + chunk['content'])

        response = requests.post(
            EMBEDDER_URL,
            json={'texts': texts}
        )

        response.raise_for_status()
        
        embeddings = np.array(
            response.json()['embeddings'],
            dtype=np.float32
        )

        all_embeddings.extend(embeddings)
        all_chunks_ids.extend(chunk_ids)
        
    update_stage(
        doc_path,
        stage = "embedding",
        status = "done",
        current = total_chunks,
        total = total_chunks,
        embeddings = len(all_embeddings)
    )
    
    return {
        'embeddings':all_embeddings,
        'chunk_ids':all_chunks_ids
    }

def generate_query_embedding(query):
    text = "query: " + query

    response = requests.post(
        EMBEDDER_URL,
        json={"texts": [text]}
    )

    response.raise_for_status()

    return response.json()['embeddings'][0]
