import argparse
from pathlib import Path

from analyzer import analyze
from extractor import extract
from chunker import chunk

parser = argparse.ArgumentParser()

subparsers = parser.add_subparsers(
    dest="command",
    required=True
)

extract_parser = subparsers.add_parser("extract")
extract_parser.add_argument("arquivo")

analyze_parser = subparsers.add_parser("analyze")
analyze_parser.add_argument("arquivo")

chunk_parser = subparsers.add_parser("chunk")
chunk_parser.add_argument("arquivo")

all_parser = subparsers.add_parser("all")
all_parser.add_argument("arquivo")

args = parser.parse_args()

path = Path(args.arquivo)
if args.command == "extract":
    extract(path)
elif args.command == "analyze":
    analyze(path)
elif args.command == "chunk":
    chunk(path)
elif args.command == "all":
    raw_path = extract(path)
    normalized_path = analyze(raw_path)
    chunks_path = chunk(normalized_path)
