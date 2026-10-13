import json
from pathlib import Path

def chunk(normalized_path):
    with open(normalized_path, "r", encoding="utf-8") as f:
        for line in f:
            block = json.loads(line)
            # print(block['paragraph_index'], block['type'], block['text'][:80])
            # TODO verificar tamanho o blocos para gerar chunk
            # TODO tokens
