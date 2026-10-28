import unittest
from unittest.mock import patch
import requests
from retrieval_service import (
    enrich_rrf_results,
    format_context_chunks,
    normalize_lexical_results,
    normalize_semantic_results,
    reciprocal_rank_fusion,
    retrieve_candidates,
    retrieve_lexical,
    retrieve_with_plan,
    select_context_chunks,
)


class TestRetrievalService(unittest.TestCase):
    @patch("retrieval_service.retrieve")
    @patch("retrieval_service.plan_query_safe")
    def test_retrieve_with_plan(self, mock_plan, mock_retrieve):
        query = "Quais são os requisitos para comprar computadores?"

        mock_plan.return_value = {
            "semantic_query": "Requisitos técnicos para aquisição de computadores",
            "keywords": ["requisitos", "computadores"],
        }

        mock_retrieve.return_value = [{"chunk_id": 10, "text": "Requisitos técnicos"}]

        result = retrieve_with_plan(query, k=3)

        mock_plan.assert_called_once_with(query)

        mock_retrieve.assert_called_once_with(
            "Requisitos técnicos para aquisição de computadores", k=3
        )

        self.assertEqual(result["original_query"], query)
        self.assertEqual(result["plan"], mock_plan.return_value)
        self.assertEqual(result["results"], mock_retrieve.return_value)

    @patch("retrieval_service.retrieve")
    @patch("query_planner.chat")
    def test_retrieve_with_fallback(self, mock_chat, mock_retrieve):
        query = "Quais são os requisitos para aquisição de computadores?"

        mock_chat.side_effect = requests.ConnectionError("LLM indisponível")

        mock_retrieve.return_value = [{"chunk_id": 15, "text": "Requisitos técnicos"}]

        result = retrieve_with_plan(query, k=3)

        mock_chat.assert_called_once()
        mock_retrieve.assert_called_once_with(query, k=3)

        self.assertEqual(result["plan"], {"semantic_query": query, "keywords": []})

        self.assertEqual(result["results"], mock_retrieve.return_value)

    @patch("retrieval_service.search_chunks")
    def test_retrieve_lexical_with_keywords(self, mock_search):
        query = "Quais são os requisitos para comprar computadores?"
        keywords = ["requisitos técnicos", "aquisição", "computadores"]

        mock_search.return_value = [{"id": 10, "content": "Especificações técnicas"}]

        result = retrieve_lexical(query, keywords, k=3)

        mock_search.assert_called_once_with(
            "requisitos técnicos aquisição computadores", limit=3
        )

        self.assertEqual(result, mock_search.return_value)

    @patch("retrieval_service.search_chunks")
    def test_retrieve_lexical_without_keywords(self, mock_search):
        query = "Quais são os requisitos para comprar computadores?"

        mock_search.return_value = [{"id": 15, "content": "Requisitos para aquisição"}]

        result = retrieve_lexical(query, [], k=3)

        mock_search.assert_called_once_with(query, limit=3)

        self.assertEqual(result, mock_search.return_value)

    @patch("retrieval_service.retrieve_lexical")
    @patch("retrieval_service.retrieve_with_plan")
    def test_retrieve_candidates(self, mock_semantic, mock_lexical):
        query = "Quais os requisitos para aquisição de computadores?"

        mock_semantic.return_value = {
            "original_query": query,
            "plan": {
                "semantic_query": "Requisitos técnicos de computadores",
                "keywords": ["requisitos", "computadores"],
            },
            "results": [
                {"chunk_id": 10, "text": "Especificações técnicas", "score": 0.85}
            ],
        }

        mock_lexical.return_value = [
            {
                "chunk_id": 15,
                "document_id": 2,
                "file_name": "edital.pdf",
                "file_path": "docs/edital.pdf",
                "content": "Requisitos de aquisição",
                "section": "Requisitos",
                "page_start": 1,
                "page_end": 1,
                "score": -2.0,
            }
        ]

        result = retrieve_candidates(query, k=3)

        mock_semantic.assert_called_once_with(query, k=3)

        mock_lexical.assert_called_once_with(query, ["requisitos", "computadores"], k=3)

        self.assertEqual(result["semantic_results"][0]["source"], "faiss")
        self.assertEqual(result["semantic_results"][0]["chunk_id"], 10)

        self.assertEqual(result["lexical_results"][0]["source"], "bm25")
        self.assertEqual(result["lexical_results"][0]["chunk_id"], 15)
        self.assertEqual(
            result["lexical_results"][0]["text"], "Requisitos de aquisição"
        )

        hybrid_results = result["hybrid_results"]

        self.assertEqual(len(hybrid_results), 2)

        hybrid_by_id = {row["chunk_id"]: row for row in hybrid_results}

        self.assertEqual(set(hybrid_by_id), {10, 15})

        self.assertEqual(hybrid_by_id[10]["sources"], ["faiss"])

        self.assertEqual(hybrid_by_id[15]["sources"], ["bm25"])

        self.assertAlmostEqual(hybrid_by_id[10]["rrf_score"], 1 / 61)

        self.assertAlmostEqual(hybrid_by_id[15]["rrf_score"], 1 / 61)

        self.assertEqual(hybrid_by_id[10]["source_scores"]["faiss"], 0.85)

        self.assertEqual(hybrid_by_id[15]["source_scores"]["bm25"], -2.0)

    def test_normalize_lexical_results(self):
        rows = [
            {
                "chunk_id": 10,
                "document_id": 2,
                "file_name": "edital.pdf",
                "file_path": "docs/edital.pdf",
                "content": "Requisitos técnicos para aquisição.",
                "section": "Especificações",
                "page_start": 3,
                "page_end": 4,
                "score": -2.5,
            }
        ]

        result = normalize_lexical_results(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chunk_id"], 10)
        self.assertEqual(result[0]["text"], rows[0]["content"])
        self.assertEqual(result[0]["score"], -2.5)
        self.assertEqual(result[0]["source"], "bm25")
        self.assertEqual(result[0]["document_id"], 2)
        self.assertNotIn("content", result[0])

    def test_normalize_semantic_results(self):
        rows = [
            {
                "chunk_id": 10,
                "document_id": 2,
                "file_name": "edital.pdf",
                "file_path": "docs/edital.pdf",
                "text": "Requisitos técnicos para aquisição.",
                "section": "Especificações",
                "page_start": 3,
                "page_end": 4,
                "score": 0.85,
            }
        ]

        result = normalize_semantic_results(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chunk_id"], 10)
        self.assertEqual(result[0]["score"], 0.85)
        self.assertEqual(result[0]["source"], "faiss")
        self.assertEqual(result[0]["document_id"], 2)
        self.assertEqual(result[0]["text"], rows[0]["text"])

        # Verifica se o dicionário original não foi alterado
        self.assertNotIn("source", rows[0])

    def test_reciprocal_rank_fusion(self):
        semantic_results = [
            {"chunk_id": 10, "score": 0.95},
            {"chunk_id": 20, "score": 0.80},
        ]

        lexical_results = [
            {"chunk_id": 20, "score": -5.0},
            {"chunk_id": 30, "score": -3.0},
        ]

        result = reciprocal_rank_fusion(semantic_results, lexical_results)

        self.assertEqual(len(result), 3)

        self.assertEqual([row["chunk_id"] for row in result], [20, 10, 30])

        self.assertAlmostEqual(result[0]["rrf_score"], 1 / 62 + 1 / 61)

    def test_enrich_rrf_results(self):
        semantic_results = [
            {
                "chunk_id": 10,
                "text": "Informações gerais",
                "source": "faiss",
                "score": 0.90,
            },
            {
                "chunk_id": 20,
                "document_id": 2,
                "file_name": "edital.pdf",
                "text": "Requisitos técnicos",
                "source": "faiss",
                "score": 0.85,
            },
        ]

        lexical_results = [
            {
                "chunk_id": 20,
                "document_id": 2,
                "file_name": "edital.pdf",
                "text": "Requisitos técnicos",
                "source": "bm25",
                "score": -2.5,
            }
        ]

        fused = [
            {"chunk_id": 20, "rrf_score": 0.0325},
            {"chunk_id": 10, "rrf_score": 0.0164},
        ]

        result = enrich_rrf_results(fused, semantic_results, lexical_results)

        self.assertEqual(len(result), 2)
        self.assertEqual([r["chunk_id"] for r in result], [20, 10])

        shared = result[0]

        self.assertEqual(shared["sources"], ["faiss", "bm25"])
        self.assertEqual(shared["source_scores"]["faiss"], 0.85)
        self.assertEqual(shared["source_scores"]["bm25"], -2.5)
        self.assertEqual(shared["document_id"], 2)
        self.assertEqual(shared["file_name"], "edital.pdf")
        self.assertEqual(shared["text"], "Requisitos técnicos")
        self.assertEqual(shared["rrf_score"], 0.0325)

        self.assertEqual(result[1]["sources"], ["faiss"])

    def test_select_context_chunks(self):
        hybrid_results = [
            {
                "chunk_id": 252,
                "text": "Compartilhamento de dados pessoais",
                "rrf_score": 0.032,
            },
            {
                "chunk_id": 226,
                "text": "O compartilhamento de dados pessoais deve ser formalizado e registrado. "
                * 2,
                "rrf_score": 0.030,
                "page_start": 30,
            },
            {
                "chunk_id": 229,
                "text": "O tratamento de dados pessoais pelo poder público exige uma base legal adequada. "
                * 2,
                "rrf_score": 0.016,
                "page_start": 32,
            },
            {
                "chunk_id": 231,
                "text": "Os órgãos públicos devem garantir transparência e os direitos dos titulares. "
                * 2,
                "rrf_score": 0.015,
            },
        ]

        result = select_context_chunks(hybrid_results, limit=2, min_chars=100)

        self.assertEqual(len(result), 2)

        self.assertEqual([row["chunk_id"] for row in result], [226, 229])

        self.assertEqual(result[0]["page_start"], 30)
        self.assertEqual(result[0]["rrf_score"], 0.030)

        self.assertEqual(select_context_chunks(hybrid_results, limit=0), [])

        self.assertEqual(len(hybrid_results), 4)

    def test_format_context_chunks(self):
        chunks = [
            {
                "chunk_id": 226,
                "file_name": "guia_anpd.pdf",
                "page_start": 30,
                "page_end": 30,
                "text": "  O compartilhamento deve ser formalizado.  ",
            },
            {
                "chunk_id": 229,
                "file_name": "guia_anpd.pdf",
                "page_start": 32,
                "page_end": 33,
                "text": "É necessária uma base legal adequada.",
            },
            {
                "chunk_id": 250,
                "file_name": "outro.pdf",
                "page_start": None,
                "page_end": None,
                "text": "Informação complementar.",
            },
        ]

        result = format_context_chunks(chunks)

        self.assertIn("[Fonte: 226]", result)
        self.assertIn("Documento: guia_anpd.pdf", result)
        self.assertIn("Página(s): 30", result)
        self.assertIn("Conteúdo: O compartilhamento deve ser formalizado.", result)

        self.assertIn("[Fonte: 229]", result)
        self.assertIn("Página(s): 32-33", result)

        self.assertIn("[Fonte: 250]", result)
        self.assertIn("Página(s): Não informada", result)

        self.assertEqual(result.count("[Fonte:"), 3)

        self.assertEqual(format_context_chunks([]), "")
