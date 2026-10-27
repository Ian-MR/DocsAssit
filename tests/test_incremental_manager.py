import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import manager
from src.paths import chunk_path, manifest_path, normalized_path, raw_path
from storage.sqlite import (
    compute_hash,
    get_chunk_ids_by_document,
    get_document_by_path,
    save_document_with_chunks,
)


class IncrementalManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = str(self.root / "rag.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_pdf(self, path: Path, content: bytes = b"pdf"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def register_indexed(self, path: Path):
        save_document_with_chunks(
            str(path),
            [{"chunk_index": 0, "content": "previously indexed"}],
            self.db_path,
        )

    def test_artifact_paths_do_not_collide_for_matching_basenames(self):
        first = self.root / "contracts" / "document.pdf"
        second = self.root / "reports" / "document.pdf"

        self.assertNotEqual(raw_path(first), raw_path(second))
        self.assertNotEqual(normalized_path(first), normalized_path(second))
        self.assertNotEqual(chunk_path(first), chunk_path(second))
        self.assertNotEqual(manifest_path(first), manifest_path(second))
        self.assertEqual(raw_path(first), raw_path(first))

    def test_sync_processes_only_new_and_changed_documents(self):
        directory = self.root / "docs"
        unchanged = self.make_pdf(directory / "unchanged.pdf")
        changed = self.make_pdf(directory / "changed.pdf", b"old")
        new_document = self.make_pdf(directory / "new.pdf")
        self.register_indexed(unchanged)
        self.register_indexed(changed)
        changed.write_bytes(b"new version")

        with patch.object(manager, "process_document", return_value="processed") as process:
            report = manager.sync_directory(directory, db_path=self.db_path)

        processed_paths = {call.args[0] for call in process.call_args_list}
        self.assertEqual(
            {changed.resolve(), new_document.resolve()},
            processed_paths,
        )
        self.assertEqual(2, len(report["processed"]))
        self.assertEqual([str(unchanged.resolve())], report["skipped"])
        self.assertEqual([], report["errors"])

    def _fake_pipeline_modules(self, index_document):
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
        indexing.index_document = index_document
        modules["indexing_service"] = indexing
        return modules

    def _prepare_pipeline(self):
        chunks_file = self.root / "generated-chunks.jsonl"
        chunks_file.write_text(
            json.dumps({"chunk_index": 0, "text": "new chunk"}) + "\n",
            encoding="utf-8",
        )
        return chunks_file

    def test_failed_indexing_keeps_old_hash_and_marks_document_error(self):
        source = self.make_pdf(self.root / "docs" / "source.pdf", b"old")
        self.register_indexed(source)
        document = get_document_by_path(str(source), self.db_path)
        old_chunk_ids = get_chunk_ids_by_document(document["id"], self.db_path)
        old_hash = compute_hash(str(source))
        source.write_bytes(b"new content")
        chunks_file = self._prepare_pipeline()
        failed_index = Mock(side_effect=RuntimeError("embedding service unavailable"))
        modules = self._fake_pipeline_modules(failed_index)

        with (
            patch.dict(sys.modules, modules),
            patch.object(manager, "ensure_manifest"),
            patch.object(
                manager,
                "load_manifest",
                return_value={"stages": {"indexing": {"chunk_ids": []}}},
            ),
            patch.object(manager, "update_stage") as update_stage,
            patch.object(manager, "chunk_path", return_value=chunks_file),
        ):
            with self.assertRaisesRegex(RuntimeError, "embedding service unavailable"):
                manager.process_document(source, db_path=self.db_path)

        document = get_document_by_path(str(source), self.db_path)
        self.assertEqual(old_hash, document["file_hash"])
        self.assertEqual("error", document["status"])
        self.assertTrue(manager.document_needs_processing(source, self.db_path))
        update_stage.assert_any_call(
            source.resolve(),
            stage="indexing",
            status="pending",
            chunk_ids=old_chunk_ids,
        )

    def test_document_is_finalized_only_after_indexing_succeeds(self):
        source = self.make_pdf(self.root / "docs" / "source.pdf", b"old")
        self.register_indexed(source)
        source.write_bytes(b"new content")
        expected_hash = compute_hash(str(source))
        chunks_file = self._prepare_pipeline()

        def verify_processing_then_return(*args, **kwargs):
            self.assertEqual(1, len(args))
            self.assertIn("progress", kwargs)
            document = get_document_by_path(str(source), self.db_path)
            self.assertEqual("processing", document["status"])

        modules = self._fake_pipeline_modules(Mock(side_effect=verify_processing_then_return))

        with (
            patch.dict(sys.modules, modules),
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

        document = get_document_by_path(str(source), self.db_path)
        self.assertEqual("processed", result)
        self.assertEqual(expected_hash, document["file_hash"])
        self.assertEqual("indexed", document["status"])


if __name__ == "__main__":
    unittest.main()
