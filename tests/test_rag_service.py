import unittest
from unittest.mock import patch

from rag_service import answer_query


class TestRagService(unittest.TestCase):
    @patch("rag_service.generate_answer")
    @patch("rag_service.select_context_chunks")
    @patch("rag_service.retrieve_candidates")
    def test_answer_query(self, mock_retrieve, mock_select, mock_generate):
        query = "Como deve ocorrer o compartilhamento de dados?"

        chunks = [
            {
                "chunk_id": 226,
                "file_name": "guia_anpd.pdf",
                "page_start": 30,
                "text": "O compartilhamento deve ser formalizado.",
                "rrf_score": 0.032,
            }
        ]

        mock_retrieve.return_value = {"hybrid_results": chunks}

        mock_select.return_value = chunks

        mock_generate.return_value = (
            "O compartilhamento deve ser formalizado [Fonte: 226]."
        )

        result = answer_query(query, k=10, context_limit=2)

        mock_retrieve.assert_called_once_with(query, k=10)

        mock_select.assert_called_once_with(chunks, limit=2)

        mock_generate.assert_called_once_with(query, chunks)

        self.assertEqual(result["query"], query)
        self.assertEqual(result["sources"], chunks)

        self.assertIn("[Fonte: 226]", result["answer"])
