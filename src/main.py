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
# chunk_parser.add_argument("--source", type=Path)

indexer_parser = subparsers.add_parser("index")
indexer_parser.add_argument("arquivo")
indexer_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)


all_parser = subparsers.add_parser("all")
all_parser.add_argument("arquivo")
all_parser.add_argument("--progress", action="store_true",help="Exibe o progresso da execução",)

embed_search = subparsers.add_parser("embed-search")
embed_search.add_argument("query")

search_parser = subparsers.add_parser("search", help="Busca chunks por palavras-chave")
search_parser.add_argument("query")
search_parser.add_argument("--limit", type=int, default=5)

args = parser.parse_args()
    
def cli_path(value: str | Path) -> Path:
    return Path(str(value).replace("\\", "/"))


def save_chunks_to_database(doc_path: Path) -> tuple[int, list[int]]:
    document_id, chunk_ids = import_chunks_jsonl(str(chunk_path(doc_path)), str(doc_path))
    print(f"Documento {document_id} salvo com {len(chunk_ids)} chunks no SQLite.")
    return document_id, chunk_ids

doc_path = Path(args.arquivo) if getattr(args, "arquivo", None) else None
progress = (
    TerminalProgress()
    if getattr(args, "progress", False)
    else None
)
if doc_path:
    ensure_manifest(doc_path)

if args.command == "extract":
    from extractor import extract

    extract(doc_path, progress=progress)
elif args.command == "analyze":
    from analyzer import analyze
    
    analyze(doc_path, progress=progress)
elif args.command == "chunk":
    from chunker import chunk

    
    chunk(doc_path, progress=progress)
    save_chunks_to_database(doc_path)
elif args.command == "index":
    from indexing_service import index_document
    
    index_document(doc_path, progress=progress)        
elif args.command == "all":
    from analyzer import analyze
    from chunker import chunk
    from extractor import extract
    from indexing_service import index_document

    extract(doc_path, progress=progress)
    analyze(doc_path, progress=progress)
    chunk(doc_path, progress=progress)
    save_chunks_to_database(doc_path)
    index_document(doc_path, progress=progress)
elif args.command == "embed-search":
    from retriever import retrieve

    results = retrieve(args.query,k=5)
    print(results)
elif args.command == "search":
    results = search_chunks(args.query, args.limit)
    print(json.dumps(
        {"query": args.query, "results": results},
        ensure_ascii=False,
        indent=2,
    ))
