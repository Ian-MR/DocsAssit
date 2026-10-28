import unittest
from unittest.mock import patch
from query_planner import plan_query, plan_query_safe

import json
from json import JSONDecodeError

import requests

class TestQueryPlanner(unittest.TestCase):


    @patch("query_planner.chat")
    def test_invalid_keywords(self, mock_chat):
        mock_chat.return_value = json.dumps({
            'semantic_query': "Aquisição de computadores",
            'keywords': "computadores"
        })
        

        with self.assertRaisesRegex(ValueError, "As palavras-chave devem ser uma lista."):
            plan_query("Quais computadores comprar?")

    @patch("query_planner.chat")
    def test_invalid_json(self, mock_chat):
        mock_chat.return_value = "Resposta inválida da LLM"

        with self.assertRaises(JSONDecodeError):
            plan_query("Quais são os requisitos do edital?")

    @patch("query_planner.chat")
    def test_empty_semantic_query(self, mock_chat):
        mock_chat.return_value = json.dumps({
            "semantic_query": "   ",
            "keywords": ["computadores", "aquisição"]
        })
    
        with self.assertRaisesRegex(ValueError, r"^Consulta semântica inválida\.$"):
            plan_query("Quais são os requisitos dos computadores?")

    @patch("query_planner.chat")
    def test_valid_plan(self, mock_chat):
        mock_chat.return_value = json.dumps({
            "semantic_query": "Requisitos técnicos para aquisição de computadores",
            "keywords": ["computadores", "aquisição", "requisitos técnicos"]
        })
    
        result = plan_query("Quais são os requisitos dos computadores?")
    
        self.assertIsInstance(result, dict)
        self.assertEqual(
            result["semantic_query"],
            "Requisitos técnicos para aquisição de computadores"
        )
        self.assertEqual(
            result["keywords"],
            ["computadores", "aquisição", "requisitos técnicos"]
        )

    @patch("query_planner.plan_query")
    def test_fallback_connection_error(self, mock_plan):
        mock_plan.side_effect = requests.ConnectionError("LLM indisponível")
    
        query = "Quais são os requisitos para aquisição de computadores?"
    
        result = plan_query_safe(query)
    
        self.assertEqual(result, {
            "semantic_query": query,
            "keywords": []
        })
    
        mock_plan.assert_called_once_with(query)

    @patch("query_planner.chat")
    def test_fallback_invalid_json(self, mock_chat):
        mock_chat.return_value = "Não consigo planejar essa consulta."
    
        query = "Quais são os requisitos do edital?"
    
        result = plan_query_safe(query)
    
        self.assertEqual(result, {
            "semantic_query": query,
            "keywords": []
        })
    
        mock_chat.assert_called_once()
