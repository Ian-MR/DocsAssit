import json
import logging
import sys
from pathlib import Path

src_dir = str(Path(__file__).resolve().parent)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from manifest import ensure_manifest, load_manifest, update_stage
from paths import chunk_path, manifest_path, normalized_path, raw_path
from storage.sqlite import (
    DB_PATH,
    compute_hash,
    delete_document_chunks,
    finalize_document_processing,
    finalize_document_deletion,
    get_document_by_path,
    get_chunk_ids_by_document,
    init_db,
    import_chunks_jsonl,
    list_documents,
    mark_document_deleted,
    mark_document_error,
    pending_deletions,
    record_deletion_error,
    start_document_processing,
)

logger = logging.getLogger(__name__)


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

    existing_document = get_document_by_path(
        str(file_path), db_path, include_deleted=True
    )
    if existing_document is not None and existing_document["status"] == "deleted":
        raise RuntimeError(
            "O documento tem uma exclusão pendente de reconciliação"
        )

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


def _remove_document_artifacts(file_path: Path) -> None:
    for artifact_path in (
        raw_path(file_path),
        normalized_path(file_path),
        chunk_path(file_path),
        manifest_path(file_path),
    ):
        try:
            artifact_path.unlink()
        except FileNotFoundError:
            continue


def _remove_index_vectors(chunk_ids: list[int], db_path: str) -> None:
    from indexer import remove_chunk_ids

    remove_chunk_ids(chunk_ids, db_path=db_path)


def reconcile_deletions(db_path: str = DB_PATH) -> dict:
    report = {"deleted": [], "errors": []}
    for job in pending_deletions(db_path):
        document_id = job["document_id"]
        file_path = Path(job["file_path"])
        try:
            chunk_ids = json.loads(job["chunk_ids"])
            _remove_index_vectors(chunk_ids, db_path)
            delete_document_chunks(document_id, db_path)
            _remove_document_artifacts(file_path)
            finalize_document_deletion(document_id, db_path)
            report["deleted"].append(str(file_path))
        except Exception as exc:
            logger.exception(
                "Failed to reconcile deletion for document %s (%s)",
                document_id,
                file_path,
            )
            try:
                record_deletion_error(document_id, str(exc), db_path)
            except Exception:
                logger.exception(
                    "Failed to record deletion error for document %s",
                    document_id,
                )
            report["errors"].append({
                "path": str(file_path),
                "error": str(exc),
            })
    return report


def _manifest_chunk_ids(file_path: Path) -> list[int]:
    try:
        manifest = load_manifest(file_path)
    except FileNotFoundError:
        return []
    indexing = manifest.get("stages", {}).get("indexing", {})
    chunk_ids = indexing.get("chunk_ids", [])
    if not isinstance(chunk_ids, list) or any(
        not isinstance(chunk_id, int) for chunk_id in chunk_ids
    ):
        raise ValueError(f"IDs de chunks inválidos no manifesto de {file_path}")
    return chunk_ids


def sync_directory(directory: Path, progress=None, db_path: str = DB_PATH) -> dict:
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)

    init_db(db_path)
    report = {"processed": [], "skipped": [], "deleted": [], "errors": []}
    reconciliation = reconcile_deletions(db_path)
    report["deleted"].extend(reconciliation["deleted"])
    report["errors"].extend(reconciliation["errors"])

    present_paths = {
        str(file_path.resolve())
        for file_path in directory.rglob("*")
        if file_path.is_file() and file_path.suffix.lower() == ".pdf"
    }
    for document in list_documents(db_path=db_path):
        file_path = Path(document["file_path"]).resolve()
        try:
            file_path.relative_to(directory)
        except ValueError:
            continue
        if str(file_path) in present_paths or document["status"] == "deleted":
            continue
        try:
            mark_document_deleted(
                document["id"],
                reason="Source file no longer exists in the watched directory",
                db_path=db_path,
            )
            try:
                manifest_chunk_ids = _manifest_chunk_ids(file_path)
            except (OSError, ValueError, json.JSONDecodeError):
                logger.exception(
                    "Could not read manifest chunk IDs for deleted document %s",
                    file_path,
                )
            else:
                mark_document_deleted(
                    document["id"],
                    extra_chunk_ids=manifest_chunk_ids,
                    db_path=db_path,
                )
        except Exception as exc:
            logger.exception(
                "Failed to mark missing document %s as deleted", file_path
            )
            report["errors"].append({
                "path": str(file_path),
                "error": str(exc),
            })

    reconciliation = reconcile_deletions(db_path)
    report["deleted"].extend(reconciliation["deleted"])
    report["errors"].extend(reconciliation["errors"])

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
            logger.exception("Failed to process document %s", file_path)
            report["errors"].append({
                "path": str(file_path),
                "error": str(exc),
            })
    return report
