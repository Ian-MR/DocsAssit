import argparse
import json
from pathlib import Path
from manifest import ensure_manifest
from paths import chunk_path, normalized_path
from progress import TerminalProgress, ProgressCallback
import sys

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from storage.sqlite import import_chunks_jsonl, search_chunks, get_chunks_by_ids

parser = argparse.ArgumentParser()

subparsers = parser.add_subparsers(
    dest="command",
    required=True
)

extract_parser = subparsers.add_parser("extract")
extract_parser.add_argument("arquivo")
extract_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)

analyze_parser = subparsers.add_parser("analyze")
analyze_parser.add_argument("arquivo")
analyze_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)

chunk_parser = subparsers.add_parser("chunk")
chunk_parser.add_argument("arquivo")
chunk_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)
chunk_parser.add_argument("--source", type=Path)

indexer_parser = subparsers.add_parser("index")
indexer_parser.add_argument("arquivo")
indexer_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)


all_parser = subparsers.add_parser("all")
all_parser.add_argument("arquivo")
all_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)

embed_search = subparsers.add_parser("embed-search")
embed_search.add_argument("query")

import_parser = subparsers.add_parser(
    "import-jsonl", help="Importa chunks JSONL existentes para o SQLite"
)
import_parser.add_argument("arquivo", type=Path)
import_parser.add_argument("--source", type=Path, required=True, help="PDF de origem")

search_parser = subparsers.add_parser("search", help="Busca chunks por palavras-chave")
search_parser.add_argument("query")
search_parser.add_argument("--limit", type=int, default=5)

args = parser.parse_args()

def index_document(doc_path, progress: ProgressCallback | None = None):
    from embedder import embed, generate_query_embedding
    from indexer import build_index

    result = embed(doc_path, progress=progress)
    build_index(result['embeddings'], result['chunk_ids'], doc_path=doc_path, progress=progress)
    return True    
    
def cli_path(value: str | Path) -> Path:
    return Path(str(value).replace("\\", "/"))


def save_chunks_to_database(source_path: Path, chunks_path: Path) -> tuple[int, list[int]]:
    document_id, chunk_ids = import_chunks_jsonl(str(chunks_path), str(source_path))
    print(f"Documento {document_id} salvo com {len(chunk_ids)} chunks no SQLite.")
    return document_id, chunk_ids


def find_source_pdf(normalized_path: Path) -> Path:
    with open(normalized_path, "r", encoding="utf-8") as f:
        first_line = next((line for line in f if line.strip()), None)
    if first_line is None:
        raise ValueError(f"O arquivo normalizado está vazio: {normalized_path}")

    block = json.loads(first_line)
    raw_path = Path(block["document_path"])
    source_path = Path("docs") / f"{raw_path.stem}.pdf"
    if not source_path.is_file():
        raise FileNotFoundError(
            f"PDF de origem não encontrado em {source_path}; "
            "informe-o com --source caminho\\para\\arquivo.pdf."
        )
    return source_path

doc_path = Path(args.arquivo)
ensure_manifest(doc_path)
progress = TerminalProgress() if args.progress else None

if args.command == "extract":
    from extractor import extract

    extract(doc_path, progress=progress)
elif args.command == "analyze":
    from analyzer import analyze
    
    analyze(doc_path, progress=progress)
elif args.command == "chunk":
    from chunker import chunk

    
    chunk(doc_path, progress=progress)
    source_path = cli_path(args.source) if args.source else find_source_pdf(normalized_path(doc_path))
    save_chunks_to_database(source_path, chunk_path(doc_path))
elif args.command == "index":
    index_document(doc_path, progress=progress)        
elif args.command == "all":
    from analyzer import analyze
    from chunker import chunk
    from extractor import extract

    source_path = cli_path(args.arquivo)

    extract(doc_path, progress=progress)
    analyze(doc_path, progress=progress)
    chunk(doc_path, progress=progress)
    save_chunks_to_database(source_path, chunk_path(doc_path))
    index_document(doc_path, progress=progress)
elif "embed-search":
    from retriever import retrieve

    results = retrieve(args.query,k=5)
    print(results)
elif args.command == "import-jsonl":
    jsonl_path = cli_path(args.arquivo)
    source_path = cli_path(args.source)
    document_id, chunk_ids = import_chunks_jsonl(
        str(jsonl_path), str(source_path)
    )
    print(f"Documento {document_id} importado com {len(chunk_ids)} chunks no SQLite.")
elif args.command == "search":
    results = search_chunks(args.query, args.limit)
    print(json.dumps(
        {"query": args0.query, "results": results},
        ensure_ascii=False,
        indent=2,
    ))
