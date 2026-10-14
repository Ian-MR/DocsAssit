import json
import tempfile
import unittest
from pathlib import Path

from storage.sqlite import import_chunks_jsonl, search_chunks


class SqliteTextSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = str(self.root / "rag.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_pdf(self, name):
        path = self.root / name
        path.write_bytes(b"test source")
        return path

    def import_chunks(self, source, records):
        jsonl_path = self.root / f"{source.stem}.jsonl"
        jsonl_path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
        return import_chunks_jsonl(str(jsonl_path), str(source), self.db_path)

    def test_search_ranks_relevant_chunks_and_returns_source(self):
        precise_pdf = self.create_pdf("precise.pdf")
        general_pdf = self.create_pdf("general.pdf")
        self.import_chunks(precise_pdf, [{
            "chunk_index": 0,
            "text": "Health insurance coverage and health insurance policy.",
            "page_start": 3,
            "page_end": 4,
            "section": "Coverage",
        }])
        self.import_chunks(general_pdf, [{
            "chunk_index": 0,
            "text": "Health coverage is important.",
            "page_start": 1,
            "page_end": 1,
            "section": "Overview",
        }])

        results = search_chunks("health insurance coverage", 5, self.db_path)

        self.assertEqual(2, len(results))
        self.assertEqual("precise.pdf", results[0]["file_name"])
        self.assertEqual((3, 4), (results[0]["page_start"], results[0]["page_end"]))
        self.assertEqual("Coverage", results[0]["section"])
        self.assertIn("insurance policy", results[0]["content"])
        self.assertLessEqual(results[0]["score"], results[1]["score"])

    def test_search_returns_empty_when_no_terms_match(self):
        source = self.create_pdf("source.pdf")
        self.import_chunks(source, [{
            "chunk_index": 0,
            "text": "Health insurance coverage.",
            "page_start": 1,
        }])

        self.assertEqual([], search_chunks("unrelated astronomy", db_path=self.db_path))

    def test_import_replaces_old_text_in_full_text_index(self):
        source = self.create_pdf("replace.pdf")
        self.import_chunks(source, [{"chunk_index": 0, "text": "old searchable phrase"}])

        self.import_chunks(source, [{"chunk_index": 0, "text": "new searchable phrase"}])

        self.assertEqual([], search_chunks("old", db_path=self.db_path))
        self.assertEqual(1, len(search_chunks("new", db_path=self.db_path)))


if __name__ == "__main__":
    unittest.main()
