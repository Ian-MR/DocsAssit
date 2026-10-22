import json
from pathlib import Path

from paths import manifest_path

def create_manifest(doc_path):
    manifest = {
        'document': str(doc_path),
        'stages': {
            'extraction': {'status': "pending"},
            'normalization': {'status': "pending"},
            'chunking': {'status': "pending"},
            'embedding': {'status': "pending"},
            'indexing': {'status': "pending", 'chunk_ids': []},
        },
    }

    with open(manifest_path(doc_path), "w", encoding="utf-8") as m:
        json.dump(manifest, m, ensure_ascii=False, indent=2)

    return True

def load_manifest(doc_path):
    with open(manifest_path(doc_path), "r", encoding="utf-8") as m:
        return json.load(m)

def save_manifest(doc_path, manifest: dict):
    with open(manifest_path(doc_path), "w", encoding="utf-8") as m:
        json.dump(manifest, m, ensure_ascii=False, indent=2)

    return True

def update_stage(doc_path, stage: str, status: str, current: int | None = None, total: int | None = None, **data):
    manifest = load_manifest(doc_path)

    stage_data = manifest['stages'][stage]
    stage_data['status'] = status

    if current is not None:
        stage_data['current'] = current

    if total is not None:
        stage_data['total'] = total

    stage_data.update(data)
    
    save_manifest(doc_path, manifest)

    return True

def ensure_manifest(doc_path):
    path = manifest_path(doc_path)
    if not path.exists():
        create_manifest(doc_path)

    return True
