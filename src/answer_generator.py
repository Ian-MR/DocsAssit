from pathlib import Path

from llm_client import chat
from retrieval_service import format_context_chunks


PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "answer_generator.md"


def generate_answer(query: str, chunks: list[dict]) -> str:
    if not chunks:
        return "Não foram encontradas evidências para responder à pergunta."

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    context = format_context_chunks(chunks)

    user_message = (
        f"Contexto documental:\n{context}\n\n"
        f"Pergunta: {query}\n\n"
        "Responda à pergunta utilizando somente o contexto documental. "
        "Cite as fontes que sustentam a resposta."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    return chat(messages, max_tokens=512)
