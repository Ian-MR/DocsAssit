import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "databases/rag.db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name     TEXT    NOT NULL,
    file_path     TEXT    NOT NULL UNIQUE,
    doc_type      TEXT    NOT NULL,                 
    file_hash     TEXT    NOT NULL,                 
    last_modified REAL    NOT NULL,                 
    status        TEXT    NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'indexed', 'error', 'outdated')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,                  
    content     TEXT    NOT NULL,
    page_start  INTEGER,
    page_end    INTEGER,
    section     TEXT,
    position    INTEGER,                            
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash  ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_conn(db_path) as conn:
        fts_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
        ).fetchone()
        conn.executescript(SCHEMA)
        if not fts_exists:
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")


def compute_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def insert_document(file_path: str, doc_type: str | None = None,
                    status: str = "pending", db_path: str = DB_PATH) -> int:
    p = Path(file_path)
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO documents (file_name, file_path, doc_type, file_hash, last_modified, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                p.name,
                str(p.resolve()),
                doc_type or p.suffix.lstrip(".").lower(),
                compute_hash(file_path),
                p.stat().st_mtime,
                status,
            ),
        )
        return cur.lastrowid


def insert_chunks(document_id: int, chunks: list[dict], db_path: str = DB_PATH) -> list[int]:
    ids = []
    with get_conn(db_path) as conn:
        for c in chunks:
            cur = conn.execute(
                """
                INSERT INTO chunks
                    (document_id, chunk_index, content, page_start, page_end, section, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    c["chunk_index"],
                    c["content"],
                    c.get("page_start"),
                    c.get("page_end"),
                    c.get("section"),
                    c.get("position"),
                ),
            )
            ids.append(cur.lastrowid)
    return ids


def save_document_with_chunks(
    file_path: str, chunks: list[dict], db_path: str = DB_PATH
) -> tuple[int, list[int]]:
    init_db(db_path)
    p = Path(file_path)
    resolved_path = str(p.resolve())
    file_hash = compute_hash(str(p))
    last_modified = p.stat().st_mtime
    doc_type = p.suffix.lstrip(".").lower()

    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM documents WHERE file_path = ?", (resolved_path,)
        ).fetchone()

        if row:
            document_id = row["id"]
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            conn.execute(
                """
                UPDATE documents
                SET file_name = ?, doc_type = ?, file_hash = ?, last_modified = ?,
                    status = 'processing', updated_at = datetime('now')
                WHERE id = ?
                """,
                (p.name, doc_type, file_hash, last_modified, document_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO documents
                    (file_name, file_path, doc_type, file_hash, last_modified, status)
                VALUES (?, ?, ?, ?, ?, 'processing')
                """,
                (p.name, resolved_path, doc_type, file_hash, last_modified),
            )
            document_id = cur.lastrowid

        chunk_ids = []
        for chunk in chunks:
            cur = conn.execute(
                """
                INSERT INTO chunks
                    (document_id, chunk_index, content, page_start, page_end, section, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    chunk["chunk_index"],
                    chunk["content"],
                    chunk.get("page_start"),
                    chunk.get("page_end"),
                    chunk.get("section"),
                    chunk.get("position"),
                ),
            )
            chunk_ids.append(cur.lastrowid)

        conn.execute(
            "UPDATE documents SET status = 'indexed', updated_at = datetime('now') WHERE id = ?",
            (document_id,),
        )

    return document_id, chunk_ids


def import_chunks_jsonl(
    jsonl_path: str, source_path: str, db_path: str = DB_PATH
) -> tuple[int, list[int]]:
    chunks = []
    position = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"JSON inválido na linha {line_number} de {jsonl_path}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Registro da linha {line_number} deve ser um objeto JSON")

            content = record.get("content", record.get("text"))
            if not isinstance(content, str):
                raise ValueError(f"Campo 'text' ou 'content' inválido na linha {line_number}")
            page_start = record.get("page_start", record.get("page_number"))
            chunks.append({
                "chunk_index": record.get("chunk_index", len(chunks)),
                "content": content,
                "page_start": page_start,
                "page_end": record.get("page_end", page_start),
                "section": record.get("section"),
                "position": record.get("position", position),
            })
            position += len(content)

    return save_document_with_chunks(source_path, chunks, db_path)


def search_chunks(
    query: str, limit: int = 5, db_path: str = DB_PATH
) -> list[dict]:
    if limit < 1:
        raise ValueError("limit deve ser maior que zero")
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    if not terms:
        return []
    match_query = " OR ".join(f'"{term}"' for term in terms)

    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.id AS chunk_id, d.id AS document_id, d.file_name, d.file_path,
                   c.page_start, c.page_end, c.section, c.content,
                   bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN documents d ON d.id = c.document_id
            WHERE chunks_fts MATCH ? AND d.status = 'indexed'
            ORDER BY score, c.id
            LIMIT ?
            """,
            (match_query, limit),
        ).fetchall()
    return [dict(row) for row in rows]

def get_document(document_id: int, db_path: str = DB_PATH) -> sqlite3.Row | None:
    with get_conn(db_path) as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def get_document_by_path(file_path: str, db_path: str = DB_PATH) -> sqlite3.Row | None:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE file_path = ?", (str(Path(file_path).resolve()),)
        ).fetchone()


def list_documents(status: str | None = None, db_path: str = DB_PATH) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        if status:
            return conn.execute("SELECT * FROM documents WHERE status = ?", (status,)).fetchall()
        return conn.execute("SELECT * FROM documents").fetchall()


def get_chunk(chunk_id: int, db_path: str = DB_PATH) -> sqlite3.Row | None:
    with get_conn(db_path) as conn:
        return conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()


def get_chunks_by_ids(chunk_ids: list[int], db_path: str = DB_PATH) -> list[sqlite3.Row]:
    if not chunk_ids:
        return []
    placeholders = ",".join("?" * len(chunk_ids))
    with get_conn(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.file_name, d.file_path
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id IN ({placeholders})
            """,
            chunk_ids,
        ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


def get_chunks_by_document(document_id: int, db_path: str = DB_PATH) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index", (document_id,)
        ).fetchall()


def get_chunk_ids_by_document(document_id: int, db_path: str = DB_PATH) -> list[int]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
    return [r["id"] for r in rows]


def has_document_changed(file_path: str, db_path: str = DB_PATH) -> bool:
    doc = get_document_by_path(file_path, db_path)
    return doc is None or doc["file_hash"] != compute_hash(file_path)

def update_document_status(document_id: int, status: str, db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, document_id),
        )


def update_document_file_info(document_id: int, db_path: str = DB_PATH) -> None:
    doc = get_document(document_id, db_path)
    p = Path(doc["file_path"])
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE documents
            SET file_hash = ?, last_modified = ?, status = 'pending', updated_at = datetime('now')
            WHERE id = ?
            """,
            (compute_hash(str(p)), p.stat().st_mtime, document_id),
        )


def update_chunk(chunk_id: int, db_path: str = DB_PATH, **fields) -> None:
    allowed = {"content", "page_start", "page_end", "section", "position", "chunk_index"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE chunks SET {set_clause} WHERE id = ?", (*fields.values(), chunk_id))

def delete_chunks_by_document(document_id: int, db_path: str = DB_PATH) -> list[int]:
    ids = get_chunk_ids_by_document(document_id, db_path)
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    return ids


def delete_document(document_id: int, db_path: str = DB_PATH) -> list[int]:
    ids = get_chunk_ids_by_document(document_id, db_path)
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return ids


if __name__ == "__main__":
    init_db()
    print(f"Schema SQLite inicializado em {DB_PATH}")