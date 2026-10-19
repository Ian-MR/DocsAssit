import json
import pymupdf4llm

from paths import raw_path

def extract(doc_path):
    input_path = doc_path
    output_path = raw_path(doc_path)
    result = pymupdf4llm.to_json(doc_path)
    raw_data = json.loads(result)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    return True
