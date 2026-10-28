import unittest
from unittest.mock import patch

from answer_generator import generate_answer, PROMPT_PATH


class TestAnswerGenerator(unittest.TestCase):
    @patch("answer_generator.chat")
    def test_generate_answer(self, mock_chat):
        mock_chat.return_value = "O compartilhamento deve ser formalizado [Fonte: 226]."

        chunks = [
            {
                "chunk_id": 226,
                "file_name": "guia_anpd.pdf",
                "page_start": 30,
                "page_end": 30,
                "text": "O compartilhamento deve ser formalizado.",
            }
        ]

        result = generate_answer("Como deve ocorrer o compartilhamento?", chunks)

        self.assertIn("[Fonte: 226]", result)

        mock_chat.assert_called_once()

        args, kwargs = mock_chat.call_args
        messages = args[0]

        self.assertEqual(
            messages[0]["content"], PROMPT_PATH.read_text(encoding="utf-8")
        )

        self.assertIn("[Fonte: 226]", messages[1]["content"])
        self.assertIn("guia_anpd.pdf", messages[1]["content"])
        self.assertIn("Página(s): 30", messages[1]["content"])
        self.assertIn("Como deve ocorrer", messages[1]["content"])

        self.assertEqual(kwargs["max_tokens"], 512)

    @patch("answer_generator.chat")
    def test_generate_answer_without_chunks(self, mock_chat):
        result = generate_answer("Qual é o requisito?", [])

        self.assertIn("Não foram encontradas evidências", result)
        mock_chat.assert_not_called()
