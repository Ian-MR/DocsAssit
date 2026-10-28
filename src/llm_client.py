import os
import requests

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080")


def chat(messages: list[dict], max_tokens: int = 256) -> str:

    data = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    response = requests.post(
        f"{LLM_BASE_URL}/v1/chat/completions", json=data, timeout=120
    )

    response.raise_for_status()

    return response.json()["choices"][0]["message"]["content"]


def count_tokens(text: str) -> int:
    response = requests.post(
        f"{LLM_BASE_URL}/tokenize", json={"content": text}, timeout=30
    )

    response.raise_for_status()

    return len(response.json()["tokens"])
