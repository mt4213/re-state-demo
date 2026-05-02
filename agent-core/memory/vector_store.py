"""
Brute-force sqlite vector store for episodic memory.
Schema: episodes(id, session_id, timestamp, reasoning_text, action_json,
                 observation_text, embedding BLOB)
UNIQUE constraint on (session_id, timestamp) — INSERT OR IGNORE for idempotency.
Search: load all rows, compute cosine similarity in Python (numpy if available,
        else stdlib math).
DB path: agent-core/state/memory.sqlite
"""
import json
import logging
import os
import sqlite3
import struct
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# Resolve DB path relative to this file: agent-core/memory/ -> agent-core/state/
_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE_DIR = os.path.join(_HERE, "..", "state")
DEFAULT_DB_PATH = os.path.normpath(os.path.join(_STATE_DIR, "memory.sqlite"))


@dataclass
class Record:
    session_id: str
    timestamp: str
    reasoning_text: str
    action_json: str
    observation_text: str
    embedding: Optional[List[float]] = None
    id: Optional[int] = None


def _pack(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: List[float], b: List[float]) -> float:
    try:
        import numpy as np
        av, bv = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
        denom = (np.linalg.norm(av) * np.linalg.norm(bv))
        if denom == 0:
            return 0.0
        return float(np.dot(av, bv) / denom)
    except ImportError:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


class VectorStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       TEXT    NOT NULL,
                timestamp        TEXT    NOT NULL,
                reasoning_text   TEXT    NOT NULL,
                action_json      TEXT    NOT NULL,
                observation_text TEXT    NOT NULL,
                embedding        BLOB,
                UNIQUE (session_id, timestamp)
            )
        """)
        self._conn.commit()

    def insert(self, record: Record) -> None:
        """Insert a record. Silently skips duplicates (session_id, timestamp)."""
        blob = _pack(record.embedding) if record.embedding is not None else None
        self._conn.execute(
            """
            INSERT OR IGNORE INTO episodes
                (session_id, timestamp, reasoning_text, action_json,
                 observation_text, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.session_id,
                record.timestamp,
                record.reasoning_text,
                record.action_json,
                record.observation_text,
                blob,
            ),
        )
        self._conn.commit()

    def search(self, embedding: List[float], k: int = 3) -> List[Record]:
        """
        Brute-force cosine search over all rows that have a stored embedding.
        Returns up to k Records sorted by descending similarity.
        """
        rows = self._conn.execute(
            "SELECT id, session_id, timestamp, reasoning_text, action_json, "
            "observation_text, embedding FROM episodes WHERE embedding IS NOT NULL"
        ).fetchall()

        scored = []
        for row in rows:
            rid, sid, ts, rt, aj, obs, blob = row
            stored_vec = _unpack(blob)
            sim = _cosine(embedding, stored_vec)
            scored.append((sim, Record(
                id=rid,
                session_id=sid,
                timestamp=ts,
                reasoning_text=rt,
                action_json=aj,
                observation_text=obs,
                embedding=stored_vec,
            )))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]

    def close(self):
        self._conn.close()


# Module-level default instance (lazy)
_store: Optional[VectorStore] = None


def get_store(db_path: str = DEFAULT_DB_PATH) -> VectorStore:
    global _store
    if _store is None or _store.db_path != db_path:
        _store = VectorStore(db_path)
    return _store
