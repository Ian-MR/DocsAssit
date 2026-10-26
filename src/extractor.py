import json
import pymupdf
import pymupdf4llm

from manifest import update_stage
from paths import raw_path
from progress import ProgressCallback, emit_progress

def extract(doc_path, progress: ProgressCallback | None = None,):
    input_path = doc_path
    output_path = raw_path(doc_path)

    doc = pymupdf.open(doc_path)
    total_pages = doc.page_count
    doc.close()

    update_stage(doc_path, stage= "extraction", status="processing", current=0, total=total_pages)    
    emit_progress(
        progress,
        stage = "extraction",
        current = 0,
        total = total_pages,
    )
    result = pymupdf4llm.to_json(doc_path)
    raw_data = json.loads(result)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
        
    update_stage(doc_path, stage= "extraction", status="done", current=total_pages, total=total_pages)    
    emit_progress(
        progress,
        stage = "extraction",
        current = total_pages,
        total = total_pages,
        done=True,
    )
    return True
