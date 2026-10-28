import json
from pathlib import Path
import requests

from llm_client import chat

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "query_planner.md"


def load_query_planner_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def plan_query(query: str) -> dict:
    messages = [
        {
            "role": "system",
            "content": load_query_planner_prompt(),
        },
        {
            "role": "user",
            "content": query,
        },
    ]

    response = chat(messages, max_tokens=256)
    result = json.loads(response)

    if not isinstance(result, dict):
        raise ValueError("O planejamento deve retornar um objeto JSON.")

    semantic_query = result.get("semantic_query")

    if not isinstance(semantic_query, str) or not semantic_query.strip():
        raise ValueError("Consulta semântica inválida.")

    keywords = result.get("keywords")

    if not isinstance(keywords, list):
        raise ValueError("As palavras-chave devem ser uma lista.")

    if len(keywords) > 5:
        raise ValueError("O planejamento deve conter no máximo 5  palavras-chave.")

    if not all(isinstance(word, str) and word.strip() for word in keywords):
        raise ValueError("As palavras-chave devem ser strings não vazias.")

    return result


def plan_query_safe(query: str) -> dict:
    try:
        return plan_query(query)
    except (ValueError, requests.RequestException):
        return {"semantic_query": query, "keywords": []}
