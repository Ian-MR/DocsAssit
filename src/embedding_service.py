from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

app = FastAPI()

print("Carregando Modelo E5...", flush=True)
model = SentenceTransformer("intfloat/multilingual-e5-small")
tokenizer = model.tokenizer
print("Modelo E5 caregado.", flush=True)

class EmbeddingRequest(BaseModel):
    texts: list[str]

@app.post("/embed")
def embed(request: EmbeddingRequest):
    embeddings = model.encode(
        request.texts,
        normalize_embeddings=True
    )

    return { "embeddings": embeddings.tolist() }

@app.post("/token-count")
def token_count(request: EmbeddingRequest):
    counts = [
        len(tokenizer.encode(text))
        for text in request.texts
    ]

    return { "token_counts": counts }
