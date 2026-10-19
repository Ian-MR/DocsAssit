from pathlib import Path

def raw_path(doc_path):
    return Path(f"raws/{doc_path.stem}.json")

def normalized_path(doc_path):
    return Path(f"normalizeds/{doc_path.stem}.jsonl")

def chunk_path(doc_path):
    return Path(f"chunks/{doc_path.stem}.jsonl")

def manifest_path(doc_path):
    return Path(f"manifests/{doc_path.stem}.json")
