import json
from paths import normalized_path, chunk_path

def chunk(doc_path):
    from transformers import AutoTokenizer

    MAX_SIZE = 400

    chunk_model = {
        'chunk_index': None,
        'document_path': None,
        'section': None,
        'page_start': None,
        'page_end': None,
        'token_count': None,
        'text': ""
    }
    
    tokenizer = AutoTokenizer.from_pretrained(
        "intfloat/multilingual-e5-small"
    )
    
    refs = {
        'current_chunk': [],
        'current_tokens': 0,
        'chunks_counter': 0,
        'current_section': None,
    }

    input_path = normalized_path(doc_path)    
    output_path = chunk_path(doc_path)

    with open(input_path, "r", encoding="utf-8") as f:
        with open(output_path, "w", encoding="utf-8") as c:
            for line in f:
                block = json.loads(line)
                text = block.get('text', "").strip()
                if not text:
                    continue
                tokens = tokenizer.encode(
                    text,
                    add_special_tokens=False
                )
                same_section = (
                    refs['current_section'] is None
                    or block['section'] == refs['current_section']
                )
                fits = refs['current_tokens'] + len(tokens) <= MAX_SIZE
                if not refs['current_chunk'] or (same_section and fits):
                    refs['current_chunk'].append(block)
                    refs['current_tokens'] += len(tokens)
                else:
                    chunk_register = chunk_model.copy()
                    chunk_register['chunk_index'] = refs['chunks_counter']
                    chunk_register['document_path'] = str(normalized_path)
                    chunk_register['section'] = refs['current_section']
                    chunk_register['page_start'] = refs['current_chunk'][0]['page_number']
                    chunk_register['page_end'] = refs['current_chunk'][-1]['page_number']
                    chunk_register['token_count'] = refs['current_tokens']
                    for chunk_block in refs['current_chunk']:
                        chunk_register['text']+= chunk_block['text']
                    c.write(json.dumps(chunk_register, ensure_ascii=False) + "\n")
                    refs['current_chunk'] = [block]
                    refs['current_tokens'] = len(tokens)
                    refs['chunks_counter']+=1
                refs['current_section'] = block['section']
            if refs['current_chunk']:
                chunk_register = chunk_model.copy()
                chunk_register['chunk_index'] = refs['chunks_counter']
                chunk_register['document_path'] = str(normalized_path)
                chunk_register['section'] = refs['current_section']
                chunk_register['page_start'] = refs['current_chunk'][0]['page_number']
                chunk_register['page_end'] = refs['current_chunk'][-1]['page_number']
                chunk_register['token_count'] = refs['current_tokens']
                for chunk_block in refs['current_chunk']:
                    chunk_register['text']+= chunk_block['text']
                c.write(json.dumps(chunk_register, ensure_ascii=False) + "\n")
    return True
