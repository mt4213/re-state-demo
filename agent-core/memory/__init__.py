"""
Memory subsystem for episodic storage and retrieval.

Components:
- embed.py: Text → 384d vectors (all-MiniLM-L6-v2)
- vector_store.py: SQLite + brute-force cosine similarity
- ingest_memory.py: Parse Phase 1 audit logs into memory entries
- recall.py: Runtime retrieval hook (Phase 3)

Usage:
    from memory import get_store, ingest_audit_log

    # Ingest past sessions
    ingest_audit_log("eval_results/chats/run1_sealed_audit.jsonl")

    # Search later
    store = get_store()
    results = store.search(embed("how to run benchmarks"), k=3)
"""

from .embed import embed
from .ingest_memory import ingest_audit_log, ingest_all_in_directory
from .vector_store import Memory, VectorStore, cosine_similarity, get_store

__all__ = [
    "embed",
    "ingest_audit_log",
    "ingest_all_in_directory",
    "Memory",
    "VectorStore",
    "cosine_similarity",
    "get_store",
]
