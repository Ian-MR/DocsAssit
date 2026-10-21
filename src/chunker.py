from embedder import count_tokens
import json
from manifest import load_manifest, update_stage
from paths import normalized_path, chunk_path
from progress import ProgressCallback, emit_progress

def read_batch(file, batch_size):
    batch = []

    for line in file:
        if not line.strip():
            continue

        batch.append(json.loads(line))

        if len(batch) >= batch_size:
            break

    return batch

def chunk(doc_path, progress: ProgressCallback | None = None):
    MAX_SIZE = 400
    TOKEN_BATCH_SIZE = 64
    
    chunk_model = {
        'chunk_index': None,
        'document_path': None,
        'section': None,
        'page_start': None,
        'page_end': None,
        'token_count': None,
        'text': ""
    }
        
    manifest = load_manifest(doc_path)
    total_blocks = manifest['stages']['normalization']['blocks']

    update_stage(
        doc_path,
        stage = "chunking",
        status = "processing",
        current = 0,
        total = total_blocks
    )

    emit_progress(
        progress,
        stage="chunking",
        current=0,
        total=total_blocks,
        message="Iniciando chunking",
    )
    
    refs = {
        'current_block': 0,
        'current_chunk': [],
        'current_tokens': 0,
        'chunks_counter': 0,
        'current_section': None,
    }

    input_path = normalized_path(doc_path)    
    output_path = chunk_path(doc_path)

    with open(input_path, "r", encoding="utf-8") as f:
        with open(output_path, "w", encoding="utf-8") as c:
            while True:
                batch = read_batch(f,TOKEN_BATCH_SIZE)
            
                if not batch:
                    break

                texts = [block['text'] for block in batch if block.get('text')]
                token_counts = iter(count_tokens(texts)) if texts else iter([])
                    
                for block in batch:
                    text = block.get('text', "").strip()
                    if not text:
                        refs['current_block']+=1
                        emit_progress(
                            progress,
                            stage = "chunking",
                            current = refs['current_block'],
                            total = total_blocks,
                        )
                        continue

                    tokens = next(token_counts)
                    
                    same_section = (
                        refs['current_section'] is None
                        or block['section'] == refs['current_section']
                    )
                    fits = refs['current_tokens'] + tokens <= MAX_SIZE
                    if not refs['current_chunk'] or (same_section and fits):
                        refs['current_chunk'].append(block)
                        refs['current_tokens'] += tokens
                    else:
                        chunk_register = chunk_model.copy()
                        chunk_register['chunk_index'] = refs['chunks_counter']
                        chunk_register['document_path'] = str(doc_path)
                        chunk_register['section'] = refs['current_section']
                        chunk_register['page_start'] = refs['current_chunk'][0]['page_number']
                        chunk_register['page_end'] = refs['current_chunk'][-1]['page_number']
                        chunk_register['token_count'] = refs['current_tokens']
                        for chunk_block in refs['current_chunk']:
                            chunk_register['text']+= chunk_block['text']
                        c.write(json.dumps(chunk_register, ensure_ascii=False) + "\n")
                        refs['current_chunk'] = [block]
                        refs['current_tokens'] = tokens
                        refs['chunks_counter']+=1
                    refs['current_section'] = block['section']
                    refs['current_block']+=1
                    emit_progress(
                        progress,
                        stage="chunking",
                        current = refs['current_block'],
                        total = total_blocks,
                    )
            if refs['current_chunk']:
                chunk_register = chunk_model.copy()
                chunk_register['chunk_index'] = refs['chunks_counter']
                chunk_register['document_path'] = str(doc_path)
                chunk_register['section'] = refs['current_section']
                chunk_register['page_start'] = refs['current_chunk'][0]['page_number']
                chunk_register['page_end'] = refs['current_chunk'][-1]['page_number']
                chunk_register['token_count'] = refs['current_tokens']
                for chunk_block in refs['current_chunk']:
                    chunk_register['text']+= chunk_block['text']
                c.write(json.dumps(chunk_register, ensure_ascii=False) + "\n")
                refs['chunks_counter']+=1
    update_stage(
        doc_path,
        stage = "chunking",
        status = "done",
        current = refs['current_block'],
        total = total_blocks,
        chunks = refs['chunks_counter'], 
    )

    emit_progress(
        progress,
        stage="chunking",
        current = refs['current_block'],
        total = total_blocks,
        message = "Chunking concluído",
        done=True,
    )
    
    return True
