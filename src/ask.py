import argparse

from rag_service import answer_query


def main():
    parser = argparse.ArgumentParser(
        description="Faça perguntas aos documentos do DocsAssist."
    )

    parser.add_argument("query", type=str, help="Pergunta que será enviada ao RAG")

    args = parser.parse_args()

    result = answer_query(args.query)

    print("\nRESPOSTA:")
    print(result["answer"])

    print("\nFONTES RECUPERADAS:")

    for source in result["sources"]:
        print(
            f"- {source['file_name']} "
            f"(página {source.get('page_start', '?')}, "
            f"chunk {source['chunk_id']})"
        )


if __name__ == "__main__":
    main()
