# Assistente de Documentos

--

A ideia é criar como protótipo um assitente que ajude na criação de documentos, buscando num base de documentos existente, e com bsae neles guiar e auxiliar a criar novos documentos.
A proposta é usar uma LLM local, junto com a técnica de Retrieval-Augmented Generation (RAG).

--

## Etapa 1 - Preparar o conjunto de dados internos

Nessa estapa é necessário preparar um banco de dados, com os arquivos que vão ser usados como fonte. Os textos são extraidos, depois são reduzidos em chunks, e depois é feito o embedding, onde ira classificar esses chunk a partir de um vetor. Então essas informações
serão armazenadas.

## Etapa 2 - Integrar com um modelo de LLM local

Nessa etepa com os dados já preparados, então é inserido um modelo de LLM local, que a partir de uma pergunta o sitema retorna documentos relevantes, com esses documentos já podemos passar isso para uma I.A. generativa, que pode analisar e auxiliar e tirar dúvidas na criação de documentos e como proseguir.

## Etapa 3 - SQLite e busca textual

Documentos e chunks são armazenados em `databases/rag.db`. A busca textual usa
FTS5/BM25 e retorna os trechos com sua fonte, página e seção.

## Local RAG

Projeto experimental de RAG local para processamento e recuperação de documentos.

O objetivo atual é construir a pipeline de preparação de documentos antes da etapa de busca semântica e recuperação.

### Docker

O projeto pode ser executado através do Docker para garantir um ambiente consistente entre diferentes sistemas operacionais e máquinas.

A aplicação utiliza uma imagem Linux com Pyrhon e todas as dependências necessárias, evitando diferenças entre ambientes locais.

### Estrutura utilizada

```text
DocsAssist/
├── docs/
├── raws/
├── normalizeds/
├── chunks/
├── databases/
├── estrutura.txt
├── README.md
├── requirements.txt
└── src
    ├── extractor.py
    ├── analyzer.py
    ├── chunker.py
    └── main.py
```

As pastas de dados são montadas como volumes no container:

```text
Host                       Container

docs/          <------>     /app/docs
raws/          <------>     /app/raws
normalizeds/   <------>     /app/normalizeds
chunks/        <------>     /app/chunks
databases/     <------>     /app/databases
```

Dessas forma, os arquivos gerados permanecem disponíveis na maquina mesmo após o container ser encerrado.


### Requisitos

É necessário possuir: 
- Docker
- Docker Compose v2

Para verificar a instalação:
```bash
docker --version
docker compose version
```

### SQLite no container

O python já possui suporte natico ao SQLite através do módulo:

```python
import sqlite3
```

Além disso, o cliente da linha de comando do SQLite é instaldo na imagem Docker para facilitar testes e inspeção do banco.

Para verificar a versão disponível no container?

```bash
docker compose run --rm --entrypoint sqlite3 docsassist --version
```

Também é possível verificar o SQLite utilizado pelo Python:

```bash
docker compose run --rm --entrypoint python docsassist \
  -c "import sqlite3; print(sqlite3.sqlite_version)"
```

### Persistência

A pasta `databases/` é persistida através do `compose.yaml`.

Os arquivos de banco não são versionados no Git. Apenas a estrutura da pasta é mantida através de `.gitkeep`.

Exemplo:

```text
databases/
└── .gitkeep
```

No `.gitignore`

```gitignore
databases/*
!databases/.gitkeep
```

### Pipeline

O fluxo implementado até o momento é:

```mermaid
flowchart TD
	A[Documento] --> B[Extractor]
	B --> C[JSON bruto]
	C --> D[Analyzer]
	D --> E[JSONL normalizado]
	E --> F[Chunker]
	F --> G[Chunks JSONL]
	G --> H[(SQLite: documents + chunks + FTS5)]
```

Os comandos `all`, `chunk` e `import-jsonl` registram o PDF e seus chunks em
`databases/rag.db`. Ao reimportar o mesmo PDF, os chunks anteriores são
substituídos e o índice FTS5 é atualizado.

#### Extractor

O `extractor.py` é responsável por ler o documento original e extrair seu conteúdo.

Atualmente, PDFs são processados utilizando `pymupdf4llm`.

A saída é armazenada em formato JSON na pasta:

```text
raws/
```

#### Analyzer

O `analyzer.py` recebe o JSON bruto produzido pelo extractor e transforma o conteúdo em blocos normalizados.

Entre os tratamentos realizados estão:
* identificação e parágrafos;
* identificação de seções;
* agrupamento de itens consecutivos de listas;
* preservação da página de origem;
* manutenção da ordem dos blocos no documento.

A saída é armazenda em JSONL:

```text
normalizeds/
```

Cada linha representa um bloco normalizado independente.

Exemplo de estrutura:
```json
{
	"document": "arquivo.pdf",
	"page": 1,
	"section": "Introdução",
	"paragraph_index": 0,
	"type": "text",
	"text": "Conteúdo do parágrafo..."
}
```

#### Chunker

O `chunker.py` agrupa os blocos normalizados em chunks para recuperação.

O tamanho dos chunks será controlado através da quantidade de tokens utilizando o tokenizer do modelo:

```text
intfloat/multilingual-e5-small
```

#### Importar JSONL existente

```bash
docker compose run --rm docsassist import-jsonl chunks/arquivo.jsonl --source docs/arquivo.pdf
```

O JSONL pode usar `text` (gerado pelo chunker) ou `content`.
Esse comando não precisa baixar o tokenizer.

#### Busca textual e contrato para API

```bash
docker compose run --rm docsassist search "health insurance coverage" --limit 5
```

A busca retorna JSON neste formato:

```json
{
  "query": "health insurance coverage",
  "results": [{
    "chunk_id": 12,
    "document_id": 3,
    "file_name": "arquivo.pdf",
    "file_path": "/app/docs/arquivo.pdf",
    "page_start": 1,
    "page_end": 2,
    "section": "Coverage",
    "content": "Trecho relevante...",
    "score": -0.75
  }]
}
```

O score BM25 mais baixo representa resultado mais relevante. Se nenhum termo
corresponder, `results` será uma lista vazia. A função
`storage.sqlite.search_chunks(query, limit)` pode ser chamada pela futura API.
### Construindo a imagem

Na raiz do projeto:
```bash
docker compose build
```

Reconstrua a imagem depois de alterar o código Python. Sem isso,
`docker compose run` pode executar uma versão antiga que não reconhece os
comandos mais novos. Para reconstruir e executar em uma única etapa:

```bash
docker compose run --build --rm docsassist all docs/arquivo.pdf
```

Ao executar no Windows, use `/` nos caminhos passados para o container
(por exemplo, `docs/arquivo.pdf`); eles são caminhos Linux dentro da imagem.

A imagem contém:
- Python
- PyTorch CPU
- Transformers
- Sentence Transformers
- PyMuPDF4LLM
- demais dependências presentes em `requirements.txt`

O PyTorch utilizado é a versão destinada à CPU, não sendo necessária uma GPU dedicada.

### Verificando a aplicação

Para visualizar os comandos disponíveis:
```bash
docker compose run --rm docsassist --help
```

Os comandos disponíveis atualmente são:
```text
extract
analyze
chunk
all
import-jsonl
search
```
#### Extração

Para processar apenas a extração de um documento:
```bash
docker compose rum --rm docsassist extract docs/arquivo.pdf
```

O resultado será salvo em:
```text
raws/
```

#### Normalização

Para normalizar apenas um arquivo previamente extraido:
```bash
docker compose rum --rm docsassist analyze raws/arquivo.json
```

O resultado será salvo em:
```text
normalizeds/
```

#### Geração de chunks

Para gerar os chunks a partir de um documento normalizado:
```bash
docker compose run --rm docsassist chunk normalizeds/arquivo.jsonl
```

Os chunks são salvos em `chunks/` e também em `databases/rag.db`. Por padrão,
o comando associa `normalizeds/arquivo.jsonl` ao PDF `docs/arquivo.pdf`.
Se o PDF estiver em outro local:
```bash
docker compose run --rm docsassist chunk normalizeds/arquivo.jsonl --source caminho/arquivo.pdf
```

O arquivo JSONL continuará disponível em:
```text
chunks/
```

#### Pipeline completo

Para executar todas as etapas em sequência:
```bash
docker compose run --rm docsassist all docs/arquivo.pdf
```

### Próximas etapas

Próximas etapas previstas:
* gerar embeddings com `sentece-transformers`;
* utilizar `intfloat/multilingual-e5-small`;
* indexar embeddings com FAISS;
* combinar busca lexical e semântica;
* adicionar processos automáticos de novos documentos.
