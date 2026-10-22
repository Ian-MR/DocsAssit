import json
from manifest import load_manifest, update_stage
from paths import raw_path, normalized_path
from progress import ProgressCallback, emit_progress

def analyze(doc_path, progress: ProgressCallback | None = None,):
    input_path = raw_path(doc_path)
    output_path = normalized_path(doc_path) 

    # Atualizar manifesto
    manifest = load_manifest(doc_path)
    total_pages = manifest['stages']['extraction']['total']

    update_stage(
        doc_path,
        stage = "normalization",
        status = "processing",
        current = 0,
        total = total_pages
    )

    emit_progress(
        progress,
        stage = "normalization",
        current = 0,
        total = total_pages,
        message = "Iniciando normalização",
    )

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_model = {
        'document_path': None,
        'page_number': None,
        'section': None,
        'type': None,
        'paragraph_index': None,
        'text': ""
    }

    class_count = {}

    refs = {
        'paragraph_index_count': 0,
        'last_section': "",
        'last_type': "",
        'current_page': 0,
        'total_blocks': 0,
    }

    block_register = None

    with open(output_path, "w", encoding="utf-8") as f:
        for page in data['pages']:
            for box in page["boxes"]:
                if not(refs['last_type'] == "list-item" and box['boxclass'] == "list-item"):
                    if block_register:
                        f.write(json.dumps(block_register, ensure_ascii=False) + "\n")
                        refs['total_blocks']+=1
                    class_count[box['boxclass']] = class_count.get(box['boxclass'],0) + 1
                    block_register = json_model.copy()
                    block_register['document_path'] = data['filename']
                    block_register['page_number'] = page['page_number']
                    block_register['type'] = box['boxclass']
                    refs['last_type'] = box['boxclass']
                    block_register['paragraph_index'] = refs['paragraph_index_count']
                    refs['paragraph_index_count']+=1
                for textline in box['textlines'] or []:
                    for span in textline['spans'] or []:
                        block_register['text'] += span['text']
                        refs['last_section'] = span['text'] if box['boxclass'] == "section-header" else refs['last_section']
                        block_register['section'] = refs['last_section']
            refs['current_page']+=1
        if block_register:
            f.write(json.dumps(block_register, ensure_ascii=False) + "\n")
            refs['total_blocks']+=1

            emit_progress(
                progress,
                stage = "normalization",
                current = refs['current_page'],
                total = total_pages,
            )
            
    update_stage(
        doc_path,
        stage = "normalization",
        status = "done",
        current = refs['current_page'],
        total = total_pages,
        blocks= refs['total_blocks']
    )
    
    emit_progress(
        progress,
        stage = "normalization",
        current = refs['current_page'],
        total = total_pages,
        message = "Normalização concluída",
        done = True,
    )
    
    return True
