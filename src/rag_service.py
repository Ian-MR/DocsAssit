from retrieval_service import retrieve_candidates, select_context_chunks

from answer_generator import generate_answer


def answer_query(query: str, k: int = 10, context_limit: int = 2) -> dict:

    retrieval = retrieve_candidates(query, k=k)

    chunks = select_context_chunks(retrieval["hybrid_results"], limit=context_limit)

    answer = generate_answer(query, chunks)

    return {"query": query, "answer": answer, "sources": chunks}
