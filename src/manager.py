import sys
from pathlib import Path

src_dir = str(Path(__file__).resolve().parent)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from manifest import ensure_manifest, load_manifest, update_stage
from paths import chunk_path
from storage.sqlite import (
    DB_PATH,
    compute_hash,
    finalize_document_processing,
    get_document_by_path,
    get_chunk_ids_by_document,
    init_db,
    import_chunks_jsonl,
    mark_document_error,
    start_document_processing,
)


def document_needs_processing(file_path: Path, db_path: str = DB_PATH) -> bool:
    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    init_db(db_path)
    document = get_document_by_path(str(file_path), db_path)
    return (
        document is None
        or document["status"] != "indexed"
        or document["file_hash"] != compute_hash(str(file_path))
    )


def process_document(
    file_path: Path,
    progress=None,
    force: bool = False,
    db_path: str = DB_PATH,
) -> str:
    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    if file_path.suffix.lower() != ".pdf":
        raise ValueError(f"Tipo de documento não suportado: {file_path}")
    if not force and not document_needs_processing(file_path, db_path):
        return "skipped"

    expected_hash = compute_hash(str(file_path))
    ensure_manifest(file_path)
    start_document_processing(str(file_path), expected_hash, db_path)

    try:
        document = get_document_by_path(str(file_path), db_path)
        previous_ids = set(
            load_manifest(file_path)["stages"]["indexing"].get("chunk_ids", [])
        )
        if document is not None:
            previous_ids.update(get_chunk_ids_by_document(document["id"], db_path))
        update_stage(
            file_path,
            stage="indexing",
            status="pending",
            chunk_ids=sorted(previous_ids),
        )

        from analyzer import analyze
        from chunker import chunk
        from extractor import extract
        from indexing_service import index_document

        extract(file_path, progress=progress)
        analyze(file_path, progress=progress)
        chunk(file_path, progress=progress)
        import_chunks_jsonl(
            str(chunk_path(file_path)),
            str(file_path),
            db_path,
            status="processing",
        )
        index_document(file_path, progress=progress)
        finalize_document_processing(str(file_path), expected_hash, db_path)
    except Exception:
        mark_document_error(str(file_path), db_path)
        raise

    return "processed"


def index_existing_document(file_path: Path, progress=None, db_path: str = DB_PATH) -> bool:
    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    expected_hash = compute_hash(str(file_path))
    ensure_manifest(file_path)
    start_document_processing(str(file_path), expected_hash, db_path)
    try:
        from indexing_service import index_document as run_indexing

        run_indexing(file_path, progress=progress)
        finalize_document_processing(str(file_path), expected_hash, db_path)
    except Exception:
        mark_document_error(str(file_path), db_path)
        raise
    return True


def sync_directory(directory: Path, progress=None, db_path: str = DB_PATH) -> dict:
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)

    report = {"processed": [], "skipped": [], "errors": []}
    for file_path in sorted(directory.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
            continue
        try:
            if not document_needs_processing(file_path, db_path):
                report["skipped"].append(str(file_path))
                continue
            result = process_document(
                file_path,
                progress=progress,
                force=True,
                db_path=db_path,
            )
            report[result].append(str(file_path))
        except Exception as exc:
            report["errors"].append({
                "path": str(file_path),
                "error": str(exc),
            })
    return report
