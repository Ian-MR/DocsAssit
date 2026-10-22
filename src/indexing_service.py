from pathlib import Path

from manifest import load_manifest, update_stage
from progress import ProgressCallback

def index_document(doc_path: Path, progress: ProgressCallback | None = None):

    from embedder import embed
    from indexer import update_index

    manifest = load_manifest(doc_path)

    old_chunk_ids = manifest['stages']['indexing'].get('chunk_ids', [])
    
    result = embed(doc_path, progress=progress)
    new_chunk_ids = result['chunk_ids']

    print(old_chunk_ids)
    print(new_chunk_ids)
    
    update_index(result['embeddings'], result['chunk_ids'], old_chunk_ids, doc_path=doc_path, progress=progress)
    return True
