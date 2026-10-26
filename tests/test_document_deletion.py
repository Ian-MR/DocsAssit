import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import manager
from storage.sqlite import (
    get_chunk_ids_by_document,
    get_chunks_by_ids,
    get_document_by_path,
    get_chunk,
    init_db,
    list_deleted_documents,
    pending_deletions,
    save_document_with_chunks,
    search_chunks,
)


class DocumentDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = str(self.root / "rag.db")
        self.directory = self.root / "docs"
        self.directory.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_pdf(self, path: Path, data: bytes = b"pdf") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def register_document(self, path: Path, text: str):
        return save_document_with_chunks(
            str(path),
            [{
                "chunk_index": 0,
                "content": text,
                "page_start": 1,
                "page_end": 1,
            }],
            self.db_path,
        )

    def test_legacy_database_migrates_to_deleted_status_without_losing_chunks(self):
        path = self.root / "legacy.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                doc_type TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                last_modified REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'processing', 'indexed', 'error', 'outdated'
                    )),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                section TEXT,
                position INTEGER,
                UNIQUE (document_id, chunk_index)
            );
            INSERT INTO documents
                (file_name, file_path, doc_type, file_hash, last_modified, status)
            VALUES ('legacy.pdf', '/legacy.pdf', 'pdf', 'hash', 0, 'indexed');
            INSERT INTO chunks (document_id, chunk_index, content)
            VALUES (1, 0, 'legacy content');
            """
        )
        connection.close()

        init_db(str(path))
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(
                [],
                connection.execute("PRAGMA foreign_key_check").fetchall(),
            )
            self.assertEqual(
                "legacy content",
                connection.execute("SELECT content FROM chunks").fetchone()[0],
            )
            connection.execute(
                "UPDATE documents SET status = 'deleted' WHERE id = 1"
            )
            connection.commit()
        finally:
            connection.close()

    def test_sync_deletes_missing_document_and_preserves_other_same_named_file(self):
        removed = self.make_pdf(self.directory / "contracts" / "same.pdf")
        retained = self.make_pdf(self.directory / "reports" / "same.pdf")
        removed_id, removed_chunks = self.register_document(
            removed, "zebracoral deleted document"
        )
        retained_id, retained_chunks = self.register_document(
            retained, "retained searchable material"
        )
        removed.unlink()

        with (
            patch.object(
                manager,
                "load_manifest",
                return_value={
                    "stages": {"indexing": {"chunk_ids": removed_chunks}}
                },
            ),
            patch.object(manager, "_remove_index_vectors") as remove_vectors,
            patch.object(manager, "_remove_document_artifacts"),
        ):
            report = manager.sync_directory(self.directory, db_path=self.db_path)

        self.assertEqual([str(removed.resolve())], report["deleted"])
        self.assertEqual([], report["errors"])
        self.assertEqual([], search_chunks("zebracoral", db_path=self.db_path))
        self.assertEqual([], get_chunks_by_ids(removed_chunks, self.db_path))
        self.assertIsNone(get_chunk(removed_chunks[0], self.db_path))
        self.assertEqual(1, len(search_chunks("retained searchable material", db_path=self.db_path)))
        self.assertEqual(retained_id, get_document_by_path(str(retained), self.db_path)["id"])
        self.assertIsNone(get_document_by_path(str(removed), self.db_path))

        history = list_deleted_documents(self.db_path)
        self.assertEqual(1, len(history))
        self.assertEqual(removed_id, history[0]["document_id"])
        self.assertEqual("same.pdf", history[0]["file_name"])
        self.assertEqual("deleted", history[0]["status"])
        self.assertIsNotNone(history[0]["deleted_at"])
        self.assertIn("no longer exists", history[0]["deletion_reason"])
        self.assertEqual(removed_chunks, remove_vectors.call_args.args[0])
        self.assertNotEqual(removed_chunks, retained_chunks)
        connection = sqlite3.connect(self.db_path)
        try:
            history_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(deleted_documents)"
                )
            }
        finally:
            connection.close()
        self.assertNotIn("content", history_columns)
        self.assertNotIn("embedding", history_columns)

    def test_intermediate_artifacts_are_removed(self):
        source = self.make_pdf(self.directory / "artifact-source.pdf")
        artifacts = [
            self.root / "raw.json",
            self.root / "normalized.jsonl",
            self.root / "chunks.jsonl",
            self.root / "manifest.json",
        ]
        for artifact in artifacts:
            artifact.write_text("sensitive derived content", encoding="utf-8")

        with (
            patch.object(manager, "raw_path", return_value=artifacts[0]),
            patch.object(manager, "normalized_path", return_value=artifacts[1]),
            patch.object(manager, "chunk_path", return_value=artifacts[2]),
            patch.object(manager, "manifest_path", return_value=artifacts[3]),
        ):
            manager._remove_document_artifacts(source)

        self.assertTrue(all(not artifact.exists() for artifact in artifacts))

    def test_failed_cleanup_keeps_document_unavailable_and_reconciles_later(self):
        source = self.make_pdf(self.directory / "source.pdf")
        document_id, chunk_ids = self.register_document(
            source, "private zebracoral content"
        )
        source.unlink()
        remove_vectors = Mock(side_effect=[OSError("FAISS file is read-only"), None])

        with (
            patch.object(manager, "_remove_index_vectors", remove_vectors),
            patch.object(manager, "_remove_document_artifacts"),
            self.assertLogs(manager.logger, level="ERROR"),
        ):
            first_report = manager.sync_directory(self.directory, db_path=self.db_path)
            live_document = get_document_by_path(
                str(source), self.db_path, include_deleted=True
            )
            self.assertEqual("deleted", live_document["status"])
            self.assertIsNone(get_document_by_path(str(source), self.db_path))
            self.assertEqual([], get_chunks_by_ids(chunk_ids, self.db_path))
            self.assertEqual(
                [],
                search_chunks("zebracoral", db_path=self.db_path),
            )
            self.assertEqual(1, len(pending_deletions(self.db_path)))

            second_report = manager.sync_directory(self.directory, db_path=self.db_path)
            third_report = manager.sync_directory(self.directory, db_path=self.db_path)

        self.assertTrue(first_report["errors"])
        self.assertEqual([str(source.resolve())], second_report["deleted"])
        self.assertEqual([], second_report["errors"])
        self.assertIsNone(get_document_by_path(str(source), self.db_path))
        self.assertEqual([], pending_deletions(self.db_path))
        self.assertEqual(document_id, list_deleted_documents(self.db_path)[0]["document_id"])
        self.assertEqual(2, remove_vectors.call_count)
        self.assertEqual([], third_report["deleted"])
        self.assertEqual([], third_report["errors"])

    def test_readded_path_creates_a_new_document_id_after_deletion(self):
        source = self.make_pdf(self.directory / "readded.pdf", b"first version")
        old_document_id, old_chunk_ids = self.register_document(
            source, "vintage obsolete material"
        )
        source.unlink()
        with (
            patch.object(manager, "_remove_index_vectors"),
            patch.object(manager, "_remove_document_artifacts"),
            patch.object(
                manager,
                "load_manifest",
                return_value={
                    "stages": {"indexing": {"chunk_ids": old_chunk_ids}}
                },
            ),
        ):
            deletion_report = manager.sync_directory(self.directory, db_path=self.db_path)
        self.assertEqual([str(source.resolve())], deletion_report["deleted"])

        source.write_bytes(b"second version")
        chunks_file = self.root / "new-chunks.jsonl"
        chunks_file.write_text(
            json.dumps({"chunk_index": 0, "text": "fresh current material"}) + "\n",
            encoding="utf-8",
        )
        fake_modules = manager_test_pipeline_modules()
        with (
            patch.dict("sys.modules", fake_modules),
            patch.object(manager, "ensure_manifest"),
            patch.object(
                manager,
                "load_manifest",
                return_value={"stages": {"indexing": {"chunk_ids": []}}},
            ),
            patch.object(manager, "update_stage"),
            patch.object(manager, "chunk_path", return_value=chunks_file),
        ):
            result = manager.process_document(source, db_path=self.db_path)

        new_document = get_document_by_path(str(source), self.db_path)
        new_chunk_ids = get_chunk_ids_by_document(new_document["id"], self.db_path)
        self.assertEqual("processed", result)
        self.assertNotEqual(old_document_id, new_document["id"])
        self.assertNotEqual(old_chunk_ids, new_chunk_ids)
        self.assertEqual([], search_chunks("vintage", db_path=self.db_path))
        self.assertEqual(1, len(search_chunks("fresh current material", db_path=self.db_path)))
        self.assertEqual(old_document_id, list_deleted_documents(self.db_path)[0]["document_id"])


def manager_test_pipeline_modules():
    import types

    modules = {}
    for module_name, function_name in (
        ("extractor", "extract"),
        ("analyzer", "analyze"),
        ("chunker", "chunk"),
    ):
        module = types.ModuleType(module_name)
        setattr(module, function_name, Mock())
        modules[module_name] = module
    indexing = types.ModuleType("indexing_service")
    indexing.index_document = Mock()
    modules["indexing_service"] = indexing
    return modules


if __name__ == "__main__":
    unittest.main()
