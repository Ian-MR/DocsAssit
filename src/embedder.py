import json
import requests
import numpy as np

from storage.sqlite import get_document_by_path, get_chunks_by_document

EMBEDDER_URL = "http://embedder:8001/embed"
DOCS_PATH = "docs/cdc_23530_DS1.pdf"


def embed():
    texts = []
    chunk_ids = []
    doc = get_document_by_path(DOCS_PATH)
    chunks = get_chunks_by_document(doc['id'])
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
    
    return embeddings, chunk_ids

def generate_query_embedding(query):
    text = "query: " + query

    response = requests.post(
        EMBEDDER_URL,
        json={"texts": [text]}
    )

    response.raise_for_status()

    return response.json()['embeddings'][0]
