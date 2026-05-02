"""
Implicit recall module — Phase 2 of implicit_memory_v1.

should_recall(reasoning) -> bool   keyword heuristic gate
recall(reasoning, k=3)  -> str|None  embed -> search -> format, capped at 500 chars

Heavy imports (embed, vector_store) are deferred inside function bodies so that
importing this module never pulls in sentence_transformers or sqlite3 at agent boot.
"""
import logging
import os

logger = logging.getLogger(__name__)

# --- Module-level constants (env-tunable) ---
MAX_RECALL_PER_SESSION = int(os.getenv("MAX_RECALL_PER_SESSION", "10"))
RECALL_SIM_THRESHOLD = float(os.getenv("RECALL_SIM_THRESHOLD", "0.35"))

_RECALL_KEYWORDS = [
    "why",
    "happened",
    "previous",
    "before",
    "crash",
    "loop",
    "earlier",
    "last time",
]


def should_recall(reasoning: str) -> bool:
    """
    Return True if reasoning contains any recall-trigger keyword (case-insensitive).
    Empty or None input returns False.
    """
    if not reasoning:
        return False
    lower = reasoning.lower()
    return any(kw in lower for kw in _RECALL_KEYWORDS)


def recall(reasoning: str, k: int = 3) -> "str | None":
    """
    Embed reasoning, search episodic memory, return a formatted context string.

    Returns None when:
    - sentence_transformers is not installed (embed returns None)
    - vector store has no rows or top similarity is below RECALL_SIM_THRESHOLD
    - any exception occurs (caught broadly — must not propagate into re_cur)

    Output format per hit:
        "<sim:0.42> reasoning_text[:120] -> action_json[:80]"
    Prefixed with "[Recalled context] " and total length capped at 500 chars.
    """
    try:
        # Deferred heavy imports
        from memory.embed import embed
        from memory.vector_store import get_store

        vec = embed(reasoning)
        if vec is None:
            return None

        store = get_store()
        hits = store.search(vec, k=k)
        if not hits:
            return None

        # Score is not directly returned by search(); we need similarity.
        # Re-compute top similarity to apply threshold check.
        # vector_store.search returns Records sorted by descending similarity but
        # doesn't expose scores.  Re-import _cosine to check the top hit.
        from memory.vector_store import _cosine, _unpack
        import struct

        def _sim(record) -> float:
            if record.embedding is None:
                return 0.0
            return _cosine(vec, record.embedding)

        top_sim = _sim(hits[0])
        if top_sim < RECALL_SIM_THRESHOLD:
            return None

        parts = []
        for rec in hits:
            sim = _sim(rec)
            rt = (rec.reasoning_text or "")[:120]
            aj = (rec.action_json or "")[:80]
            parts.append(f"<sim:{sim:.2f}> {rt} -> {aj}")

        body = " | ".join(parts)
        prefix = "[Recalled context] "
        combined = prefix + body

        # Cap total at 500 chars
        if len(combined) > 500:
            combined = combined[:500]

        return combined

    except Exception:
        logger.exception("recall() failed — returning None")
        return None
