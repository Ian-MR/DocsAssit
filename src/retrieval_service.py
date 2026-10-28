from query_planner import plan_query_safe
from retriever import retrieve
from storage.sqlite import search_chunks


def retrieve_with_plan(query: str, k: int = 5) -> dict:
    plan = plan_query_safe(query)

    chunks = retrieve(plan["semantic_query"], k=k)

    return {"original_query": query, "plan": plan, "results": chunks}


def retrieve_lexical(query: str, keywords: list[str], k: int = 5) -> list[dict]:
    lexical_query = " ".join(keywords) if keywords else query

    return search_chunks(lexical_query, limit=k)


def retrieve_candidates(query: str, k: int = 5) -> dict:
    semantic_data = retrieve_with_plan(query, k=k)
    lexical_results = retrieve_lexical(query, semantic_data["plan"]["keywords"], k=k)

    semantic_results = normalize_semantic_results(semantic_data["results"])
    lexical_results = normalize_lexical_results(lexical_results)

    fused = reciprocal_rank_fusion(semantic_results, lexical_results)

    hybrid_results = enrich_rrf_results(fused, semantic_results, lexical_results)

    return {
        "original_query": query,
        "plan": semantic_data["plan"],
        "semantic_results": semantic_results,
        "lexical_results": lexical_results,
        "hybrid_results": hybrid_results,
    }


def normalize_lexical_results(results: list[dict]) -> list[dict]:
    normalized = []

    for row in results:
        normalized.append(
            {
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "file_name": row["file_name"],
                "file_path": row["file_path"],
                "text": row["content"],
                "section": row["section"],
                "page_start": row["page_start"],
                "page_end": row["page_end"],
                "score": row["score"],
                "source": "bm25",
            }
        )

    return normalized


def normalize_semantic_results(results: list[dict]) -> list[dict]:
    return [{**row, "source": "faiss"} for row in results]


def reciprocal_rank_fusion(
    semantic_results: list[dict], lexical_results: list[dict], rank_constant: int = 60
) -> list[dict]:
    scores = {}

    for ranking in (semantic_results, lexical_results):
        for position, row in enumerate(ranking, start=1):
            chunk_id = row["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (
                rank_constant + position
            )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    return [{"chunk_id": chunk_id, "rrf_score": score} for chunk_id, score in ranked]


def enrich_rrf_results(
    fused: list[dict], semantic_results: list[dict], lexical_results: list[dict]
) -> list[dict]:
    records = {}
    for row in semantic_results + lexical_results:
        chunk_id = row["chunk_id"]
        if chunk_id not in records:
            records[chunk_id] = {
                key: value
                for key, value in row.items()
                if key not in ("score", "source")
            }

            records[chunk_id]["sources"] = []
            records[chunk_id]["source_scores"] = {}

        source = row["source"]

        if source not in records[chunk_id]["sources"]:
            records[chunk_id]["sources"].append(source)

        records[chunk_id]["source_scores"][source] = row["score"]

    return [
        {**records[item["chunk_id"]], "rrf_score": item["rrf_score"]} for item in fused
    ]


def select_context_chunks(
    hybrid_results: list[dict], limit: int = 3, min_chars: int = 100
) -> list[dict]:

    if limit <= 0:
        return []

    selected = []

    for row in hybrid_results:
        text = row.get("text", "").strip()

        if len(text) < min_chars:
            continue

        selected.append(row)

        if len(selected) >= limit:
            break

    return selected


def format_context_chunks(chunks: list[dict]) -> str:
    blocks = []

    for row in chunks:
        chunk_id = row["chunk_id"]
        file_name = row.get("file_name") or "Desconhecido"
        page_start = row.get("page_start")
        page_end = row.get("page_end")

        if page_start is None:
            pages = "Não informada"
        elif page_end is None or page_start == page_end:
            pages = str(page_start)
        else:
            pages = f"{page_start}-{page_end}"

        text = row["text"].strip()

        block = (
            f"[Fonte: {chunk_id}]\n"
            f"Documento: {file_name}\n"
            f"Página(s): {pages}\n"
            f"Conteúdo: {text}"
        )

        blocks.append(block)

    return "\n\n".join(blocks)
