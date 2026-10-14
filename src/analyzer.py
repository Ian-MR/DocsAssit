import json
from pathlib import Path

'''
Recebe o path de um raw e retorna o path dele normalizado
'''
def analyze(raw_path):
    with open(raw_path, "r", encoding="utf-8") as f:
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
        'last_type': ""
    }

    block_register = None

    with open(f"normalizeds/{raw_path.stem}.jsonl", "w", encoding="utf-8") as f:
        for page in data['pages']:
            for box in page["boxes"]:
                if not(refs['last_type'] == "list-item" and box['boxclass'] == "list-item"):
                    if block_register:
                        f.write(json.dumps(block_register, ensure_ascii=False) + "\n")
                    class_count[box['boxclass']] = class_count.get(box['boxclass'],0) + 1
                    block_register = json_model.copy()
                    block_register['document_path'] = data['filename']
                    block_register['page_number'] = page['page_number']
                    block_register['type'] = box['boxclass']
                    refs['last_type'] = box['boxclass']
                    block_register['paragraph_index'] = refs['paragraph_index_count']
                    refs['paragraph_index_count']+=1
                for textline in box['textlines']:
                    for span in textline['spans']:
                        block_register['text'] += span['text']
                        refs['last_section'] = span['text'] if box['boxclass'] == "section-header" else refs['last_section']
                        block_register['section'] = refs['last_section']
        f.write(json.dumps(block_register, ensure_ascii=False) + "\n")
    print(class_count)
    return Path(f"normalizeds/{raw_path.stem}.jsonl")
