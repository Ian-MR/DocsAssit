import hashlib
from pathlib import Path


def _artifact_name(doc_path):
    path = Path(doc_path).resolve()
    path_hash = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return f"{path.stem}-{path_hash}"


def raw_path(doc_path):
    return Path("raws") / f"{_artifact_name(doc_path)}.json"

def normalized_path(doc_path):
    return Path("normalizeds") / f"{_artifact_name(doc_path)}.jsonl"

def chunk_path(doc_path):
    return Path("chunks") / f"{_artifact_name(doc_path)}.jsonl"

def manifest_path(doc_path):
    return Path("manifests") / f"{_artifact_name(doc_path)}.json"
