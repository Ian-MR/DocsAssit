import json
import requests
import numpy as np

from manifest import update_stage
from storage.sqlite import get_document_by_path, get_chunks_by_document

EMBEDDER_URL = "http://embedder:8001/embed"

def count_tokens(texts: list[str]) -> list[str]:
    response = requests.post(
        "http://embedder:8001/token-count",
        json={'texts': texts },
    )

    response.raise_for_status()

    return response.json()['token_counts']

def embed(doc_path):
    texts = []
    chunk_ids = []
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
    
    for chunk in chunks:
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

    update_stage(
        doc_path,
        stage = "embedding",
        status = "done",
        current = total_chunks,
        total = total_chunks,
        embeddings = len(embeddings)
    )
    
    return {
        'embeddings':embeddings,
        'chunk_ids':chunk_ids
    }

def generate_query_embedding(query):
    text = "query: " + query

    response = requests.post(
        EMBEDDER_URL,
        json={"texts": [text]}
    )

    response.raise_for_status()

    return response.json()['embeddings'][0]
