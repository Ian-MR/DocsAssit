from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

app = FastAPI()

model = SentenceTransformer(
    "intfloat/multilingual-e5-small"
)

class EmbeddingRequest(BaseModel):
    texts: list[str]

@app.post("/embed")
def embed(request: EmbeddingRequest):
    embeddings = model.encode(
        request.texts,
        normalize_embeddings=True
    )

    return {
        "embeddings": embeddings.tolist()
    }
