import unittest
from unittest.mock import patch

from llm_client import count_tokens, LLM_BASE_URL


class TestLLMClient(unittest.TestCase):
    @patch("llm_client.requests.post")
    def test_count_tokens(self, mock_post):
        text = "Quais são os requisitos técnicos?"

        mock_post.return_value.json.return_value = {
            "tokens": [101, 205, 309, 412, 518, 620]
        }

        result = count_tokens(text)

        self.assertEqual(result, 6)

        mock_post.assert_called_once_with(
            f"{LLM_BASE_URL}/tokenize", json={"content": text}, timeout=30
        )

        mock_post.return_value.raise_for_status.assert_called_once_with()
