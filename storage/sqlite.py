import hashlib
import json
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "databases/rag.db")
logger = logging.getLogger(__name__)

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
                  CHECK (status IN ('pending', 'processing', 'indexed', 'error', 'outdated', 'deleted')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    deleted_at    TEXT,
    deletion_reason TEXT
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

CREATE TABLE IF NOT EXISTS deleted_documents (
    document_id             INTEGER PRIMARY KEY,
    file_name               TEXT NOT NULL,
    file_path               TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status = 'deleted'),
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    deleted_at              TEXT NOT NULL,
    deletion_reason         TEXT,
    replacement_document_id INTEGER
);

CREATE TABLE IF NOT EXISTS deletion_jobs (
    document_id INTEGER PRIMARY KEY,
    chunk_ids   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'error')),
    error       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

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


def _migrate_documents_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        table = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if table is None:
            return
        if (
            "'deleted'" in (table[0] or "")
            and {"deleted_at", "deletion_reason"}.issubset(columns)
        ):
            return

        conn.execute("BEGIN")
        conn.execute("DROP TABLE IF EXISTS documents_new")
        conn.execute(
            """
            CREATE TABLE documents_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name     TEXT NOT NULL,
                file_path     TEXT NOT NULL UNIQUE,
                doc_type      TEXT NOT NULL,
                file_hash     TEXT NOT NULL,
                last_modified REAL NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN (
                                  'pending', 'processing', 'indexed', 'error',
                                  'outdated', 'deleted'
                              )),
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
                deleted_at    TEXT,
                deletion_reason TEXT
            )
            """
        )
        target_columns = (
            "id, file_name, file_path, doc_type, file_hash, last_modified, "
            "status, created_at, updated_at, deleted_at, deletion_reason"
        )
        source_columns = (
            "id",
            "file_name",
            "file_path",
            "doc_type",
            "file_hash",
            "last_modified",
            "status",
            "created_at",
            "updated_at",
            "deleted_at",
            "deletion_reason",
        )
        selections = [
            name if name in columns else "NULL"
            for name in source_columns
        ]
        conn.execute(
            f"INSERT INTO documents_new ({target_columns}) "
            f"SELECT {', '.join(selections)} FROM documents"
        )
        conn.execute("DROP TABLE documents")
        conn.execute("ALTER TABLE documents_new RENAME TO documents")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)"
        )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"Document table migration caused foreign-key violations: {violations}"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Failed to migrate documents table in %s", db_path)
        raise
    finally:
        conn.close()


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
    _migrate_documents_table(db_path)


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
    file_path: str,
    chunks: list[dict],
    db_path: str = DB_PATH,
    status: str = "indexed",
) -> tuple[int, list[int]]:
    if status not in {"pending", "processing", "indexed", "error", "outdated"}:
        raise ValueError(f"Status de documento inválido: {status}")

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
            existing_status = conn.execute(
                "SELECT status FROM documents WHERE id = ?", (document_id,)
            ).fetchone()["status"]
            if existing_status == "deleted":
                raise RuntimeError(
                    "Não é possível reimportar documento antes da limpeza de exclusão"
                )
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            if status == "processing":
                conn.execute(
                    """
                    UPDATE documents
                    SET file_name = ?, doc_type = ?, status = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (p.name, doc_type, status, document_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE documents
                    SET file_name = ?, doc_type = ?, file_hash = ?, last_modified = ?,
                        status = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (p.name, doc_type, file_hash, last_modified, status, document_id),
                )
        else:
            cur = conn.execute(
                """
                INSERT INTO documents
                    (file_name, file_path, doc_type, file_hash, last_modified, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (p.name, resolved_path, doc_type, file_hash, last_modified, status),
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

    return document_id, chunk_ids


def import_chunks_jsonl(
    jsonl_path: str,
    source_path: str,
    db_path: str = DB_PATH,
    status: str = "indexed",
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

    return save_document_with_chunks(source_path, chunks, db_path, status)


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
        return conn.execute(
            "SELECT * FROM documents WHERE id = ? AND status != 'deleted'",
            (document_id,),
        ).fetchone()


def get_document_by_path(
    file_path: str,
    db_path: str = DB_PATH,
    include_deleted: bool = False,
) -> sqlite3.Row | None:
    deleted_filter = "" if include_deleted else " AND status != 'deleted'"
    with get_conn(db_path) as conn:
        return conn.execute(
            f"SELECT * FROM documents WHERE file_path = ?{deleted_filter}",
            (str(Path(file_path).resolve()),),
        ).fetchone()


def list_documents(status: str | None = None, db_path: str = DB_PATH) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        if status:
            return conn.execute("SELECT * FROM documents WHERE status = ?", (status,)).fetchall()
        return conn.execute("SELECT * FROM documents").fetchall()


def get_chunk(chunk_id: int, db_path: str = DB_PATH) -> sqlite3.Row | None:
    with get_conn(db_path) as conn:
        return conn.execute(
            """
            SELECT c.* FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id = ? AND d.status = 'indexed'
            """,
            (chunk_id,),
        ).fetchone()


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
            WHERE c.id IN ({placeholders}) AND d.status = 'indexed'
            """,
            chunk_ids,
        ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


def get_chunks_by_document(document_id: int, db_path: str = DB_PATH) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            """
            SELECT c.* FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.document_id = ? AND d.status IN ('indexed', 'processing')
            ORDER BY c.chunk_index
            """,
            (document_id,),
        ).fetchall()


def get_chunk_ids_by_document(document_id: int, db_path: str = DB_PATH) -> list[int]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
    return [r["id"] for r in rows]


def has_document_changed(file_path: str, db_path: str = DB_PATH) -> bool:
    doc = get_document_by_path(file_path, db_path)
    return doc is None or doc["file_hash"] != compute_hash(file_path)


def start_document_processing(
    file_path: str, expected_hash: str, db_path: str = DB_PATH
) -> int:
    init_db(db_path)
    path = Path(file_path).resolve()
    last_modified = path.stat().st_mtime

    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id, status FROM documents WHERE file_path = ?", (str(path),)
        ).fetchone()
        if row:
            document_id = row["id"]
            if row["status"] == "deleted":
                raise RuntimeError(
                    "Não é possível reprocessar o documento enquanto a exclusão "
                    "não tiver sido reconciliada"
                )
            conn.execute(
                """
                UPDATE documents
                SET status = 'processing', updated_at = datetime('now')
                WHERE id = ?
                """,
                (document_id,),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO documents
                    (file_name, file_path, doc_type, file_hash, last_modified, status)
                VALUES (?, ?, ?, ?, ?, 'processing')
                """,
                (
                    path.name,
                    str(path),
                    path.suffix.lstrip(".").lower(),
                    expected_hash,
                    last_modified,
                ),
            )
            document_id = cur.lastrowid
    return document_id


def finalize_document_processing(
    file_path: str, expected_hash: str, db_path: str = DB_PATH
) -> None:
    path = Path(file_path).resolve()
    actual_hash = compute_hash(str(path))
    if actual_hash != expected_hash:
        raise RuntimeError(f"O documento foi alterado durante o processamento: {path}")

    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE documents
            SET file_hash = ?, last_modified = ?, status = 'indexed',
                updated_at = datetime('now')
            WHERE file_path = ? AND status = 'processing'
            """,
            (actual_hash, path.stat().st_mtime, str(path)),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"Documento não encontrado para finalizar: {path}")


def mark_document_error(file_path: str, db_path: str = DB_PATH) -> None:
    document = get_document_by_path(file_path, db_path)
    if document is not None:
        update_document_status(document["id"], "error", db_path)


def update_document_status(document_id: int, status: str, db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = ?, updated_at = datetime('now') "
            "WHERE id = ? AND status != 'deleted'",
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
    return mark_document_deleted(document_id, db_path=db_path)


def mark_document_deleted(
    document_id: int,
    reason: str | None = None,
    extra_chunk_ids: list[int] | None = None,
    db_path: str = DB_PATH,
) -> list[int]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        document = conn.execute(
            "SELECT status, deleted_at, deletion_reason FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if document is None:
            return []

        chunk_ids = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        }
        chunk_ids.update(extra_chunk_ids or [])
        existing_job = conn.execute(
            "SELECT chunk_ids FROM deletion_jobs WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if existing_job:
            chunk_ids.update(json.loads(existing_job["chunk_ids"]))

        conn.execute(
            """
            UPDATE documents
            SET status = 'deleted', deleted_at = COALESCE(deleted_at, datetime('now')),
                deletion_reason = COALESCE(deletion_reason, ?),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (reason, document_id),
        )
        conn.execute(
            """
            INSERT INTO deletion_jobs (document_id, chunk_ids, status, error, updated_at)
            VALUES (?, ?, 'pending', NULL, datetime('now'))
            ON CONFLICT(document_id) DO UPDATE SET
                chunk_ids = excluded.chunk_ids,
                status = 'pending',
                error = NULL,
                updated_at = datetime('now')
            """,
            (document_id, json.dumps(sorted(chunk_ids))),
        )
    return sorted(chunk_ids)


def pending_deletions(db_path: str = DB_PATH) -> list[sqlite3.Row]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        return conn.execute(
            """
            SELECT j.document_id, j.chunk_ids, j.status AS job_status, j.error,
                   d.file_name, d.file_path, d.status, d.created_at, d.updated_at,
                   d.deleted_at, d.deletion_reason
            FROM deletion_jobs j
            JOIN documents d ON d.id = j.document_id
            WHERE d.status = 'deleted'
            ORDER BY j.document_id
            """
        ).fetchall()


def delete_document_chunks(document_id: int, db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM chunks WHERE document_id = ? AND EXISTS "
            "(SELECT 1 FROM documents WHERE id = ? AND status = 'deleted')",
            (document_id, document_id),
        )


def record_deletion_error(
    document_id: int, error: str, db_path: str = DB_PATH
) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE deletion_jobs
            SET status = 'error', error = ?, updated_at = datetime('now')
            WHERE document_id = ?
            """,
            (error, document_id),
        )


def finalize_document_deletion(document_id: int, db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        document = conn.execute(
            """
            SELECT d.id, d.file_name, d.file_path, d.status, d.created_at,
                   d.updated_at, d.deleted_at, d.deletion_reason
            FROM documents d
            JOIN deletion_jobs j ON j.document_id = d.id
            WHERE d.id = ? AND d.status = 'deleted'
            """,
            (document_id,),
        ).fetchone()
        if document is None:
            return

        conn.execute(
            """
            INSERT INTO deleted_documents (
                document_id, file_name, file_path, status, created_at, updated_at,
                deleted_at, deletion_reason
            )
            VALUES (?, ?, ?, 'deleted', ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                file_name = excluded.file_name,
                file_path = excluded.file_path,
                status = 'deleted',
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                deleted_at = excluded.deleted_at,
                deletion_reason = excluded.deletion_reason
            """,
            (
                document["id"],
                document["file_name"],
                document["file_path"],
                document["created_at"],
                document["updated_at"],
                document["deleted_at"],
                document["deletion_reason"],
            ),
        )
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.execute("DELETE FROM deletion_jobs WHERE document_id = ?", (document_id,))


def list_deleted_documents(db_path: str = DB_PATH) -> list[sqlite3.Row]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM deleted_documents ORDER BY deleted_at, document_id"
        ).fetchall()


def document_has_pending_deletion(
    document_id: int, db_path: str = DB_PATH
) -> bool:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM deletion_jobs WHERE document_id = ?", (document_id,)
        ).fetchone() is not None


if __name__ == "__main__":
    init_db()
    print(f"Schema SQLite inicializado em {DB_PATH}")