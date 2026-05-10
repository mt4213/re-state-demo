"""
SQLite-based vector store for episodic memories.
Brute-force cosine similarity; ANN index optional for >10k rows.

Uses stdlib struct/array for encoding to avoid numpy dependency in-container.
"""
from __future__ import annotations

import dataclasses as dc
import json
import math
import sqlite3
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = __import__("logging").getLogger(__name__)

# Default location: agent-core/state/memory.sqlite (mounted into container)
DEFAULT_DB_PATH = Path(__file__).parent.parent / "state" / "memory.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    embedding BLOB NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    origin TEXT NOT NULL,
    validated INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_origin ON memories(origin);
CREATE INDEX IF NOT EXISTS idx_memories_validated ON memories(validated);
"""


@dc.dataclass
class Memory:
    """A single episodic memory entry."""
    content: str
    embedding: list[float]  # 384-d vector from all-MiniLM-L6-v2
    metadata: dict
    created_at: str
    origin: str = "live"  # "bootstrap" or "live"
    validated: bool = False
    id: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "origin": self.origin,
            "validated": self.validated,
        }


def _encode_embedding(vec: list[float]) -> bytes:
    """Pack float32 vector into bytes for SQLite BLOB storage."""
    # Use struct.pack with 'f' format (float32) for each element
    return struct.pack(f"{len(vec)}f", *vec)


def _decode_embedding(blob: bytes) -> list[float]:
    """Unpack SQLite BLOB back to float32 vector."""
    # Unpack as float32 array
    fmt = f"{len(blob) // 4}f"  # 4 bytes per float32
    return list(struct.unpack(fmt, blob))


def _dot(a: list[float], b: list[float]) -> float:
    """Compute dot product."""
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    """Compute L2 norm."""
    return math.sqrt(sum(x * x for x in a))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = _norm(a)
    norm_b = _norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return _dot(a, b) / (norm_a * norm_b)


class ANNIndexStub:
    """
    Stub for approximate nearest neighbor index (faiss/usearch).

    For scale >10k rows, swap brute-force for ANN search:
    - pip install faiss-cpu  (or faiss-gpu for CUDA)
    - Build index on store.count() crossing threshold
    - Query index instead of scanning all rows

    Interface:
        index = ANNIndexStub(embedding_dim=384)
        index.add(memory_id, embedding)
        results = index.search(query_embedding, k=5) -> [(id, score), ...]
    """

    def __init__(self, embedding_dim: int = 384):
        self.embedding_dim = embedding_dim
        self._built = False

    def add(self, memory_id: int, embedding: list[float]) -> None:
        """Add vector to index."""
        # TODO: Implement with faiss.IndexFlatIP or usearch
        pass

    def search(
        self, query: list[float], k: int = 5
    ) -> list[tuple[int, float]]:
        """Return top-k (id, score) pairs."""
        # TODO: Implement ANN search
        return []

    def is_built(self) -> bool:
        """Check if index has been built."""
        return self._built


class VectorStore:
    """
    Thread-safe SQLite vector store with brute-force cosine search.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def add(self, memory: Memory) -> int:
        """Add a memory entry. Returns the new row ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO memories
               (embedding, content, metadata_json, created_at, origin, validated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                _encode_embedding(memory.embedding),
                memory.content,
                json.dumps(memory.metadata),
                memory.created_at,
                memory.origin,
                1 if memory.validated else 0,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def get(self, memory_id: int) -> Memory | None:
        """Retrieve a memory by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            return None
        return _row_to_memory(row)

    def search(
        self,
        query_embedding: list[float],
        k: int = 5,
        min_similarity: float = 0.0,
        origin: str | None = None,
        validated_only: bool = False,
    ) -> list[tuple[Memory, float]]:
        """
        Brute-force cosine similarity search.
        Returns list of (memory, similarity) sorted by similarity DESC.
        """
        query_vec = list(query_embedding)  # Ensure list type

        # Build WHERE clause
        where_parts = []
        params: list = []
        if origin:
            where_parts.append("origin = ?")
            params.append(origin)
        if validated_only:
            where_parts.append("validated = 1")

        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        # Fetch all candidates
        conn = self._get_conn()
        rows = conn.execute(
            f"SELECT id, embedding, content, metadata_json, created_at, origin, validated "
            f"FROM memories {where_sql}",
            params,
        ).fetchall()

        # Compute similarities
        results: list[tuple[Memory, float]] = []
        for row in rows:
            emb = _decode_embedding(row["embedding"])
            sim = cosine_similarity(query_vec, emb)
            if sim >= min_similarity:
                mem = Memory(
                    id=row["id"],
                    content=row["content"],
                    embedding=emb,
                    metadata=json.loads(row["metadata_json"]),
                    created_at=row["created_at"],
                    origin=row["origin"],
                    validated=bool(row["validated"]),
                )
                results.append((mem, sim))

        # Sort by similarity DESC
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    def count(self) -> int:
        """Total number of memories stored."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()
        return row["cnt"]

    def stats(self) -> dict:
        """Basic statistics about the store."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()["cnt"]
        bootstrap = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE origin = 'bootstrap'"
        ).fetchone()["cnt"]
        live = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE origin = 'live'"
        ).fetchone()["cnt"]
        validated = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE validated = 1"
        ).fetchone()["cnt"]
        return {
            "total": total,
            "bootstrap": bootstrap,
            "live": live,
            "validated": validated,
        }

    def delete(self, memory_id: int) -> bool:
        """Delete a memory by ID. Returns True if deleted."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the connection for this thread."""
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            delattr(self._local, "conn")


def _row_to_memory(row: sqlite3.Row) -> Memory:
    """Convert database row to Memory object."""
    return Memory(
        id=row["id"],
        content=row["content"],
        embedding=_decode_embedding(row["embedding"]),
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
        origin=row["origin"],
        validated=bool(row["validated"]),
    )


# Singleton instance for convenience
_default_store: VectorStore | None = None


def get_store(db_path: Path | str | None = None) -> VectorStore:
    """Get or create the default VectorStore instance."""
    global _default_store
    if _default_store is None:
        _default_store = VectorStore(db_path or DEFAULT_DB_PATH)
    return _default_store
