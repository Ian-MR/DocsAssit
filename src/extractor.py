import json
from pathlib import Path
import pymupdf4llm

'''
recebe path de um documento e retorna o path de um json gerado pelo PyMuPDF4LLM
'''
def extract(doc_path):
    result = pymupdf4llm.to_json(doc_path)
    raw_data = json.loads(result)
    with open(f"raws/{doc_path.stem}.json", "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    return Path(f"raws/{doc_path.stem}.json")
