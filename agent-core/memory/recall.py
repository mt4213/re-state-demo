"""
Implicit recall module — Phase 3 of implicit_memory_v1.

should_recall(reasoning) -> bool   keyword heuristic gate
recall(reasoning, k=3)  -> str|None  embed -> search -> format, capped at 500 chars
recall_context(context, k=3) -> str|None  richer context with live-origin preference

Heavy imports (embed, vector_store) are deferred inside function bodies so that
importing this module never pulls in sentence_transformers or sqlite3 at agent boot.
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# --- Module-level constants (env-tunable) ---
MAX_RECALL_PER_SESSION = int(os.getenv("MAX_RECALL_PER_SESSION", "10"))
RECALL_SIM_THRESHOLD = float(os.getenv("RECALL_SIM_THRESHOLD", "0.35"))
# Context budget in tokens (~4 chars per token)
RECALL_MAX_TOKENS = int(os.getenv("RECALL_MAX_TOKENS", "2000"))

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


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def should_recall(reasoning: str) -> bool:
    """
    Return True if reasoning contains any recall-trigger keyword (case-insensitive).
    Empty or None input returns False.
    """
    if not reasoning:
        return False
    lower = reasoning.lower()
    return any(kw in lower for kw in _RECALL_KEYWORDS)


def _search_with_live_preference(
    query_embedding: list[float],
    k: int,
    min_similarity: float,
    store: "Any | None" = None,
) -> "list[tuple[Any, float]]":
    """
    Search memory store with preference for live-origin memories.

    Returns top-k results where 'live' origin is preferred over 'bootstrap':
    - Fetch top-k live memories first
    - Fill remaining slots with bootstrap if needed
    - Never let bootstrap displace live at equal similarity

    Args:
        query_embedding: Query vector
        k: Maximum number of results to return
        min_similarity: Minimum similarity threshold
        store: Optional VectorStore instance (for testing); defaults to get_store()

    Returns list of (Memory, similarity) tuples.
    """
    from memory.vector_store import get_store

    if store is None:
        store = get_store()

    # First, get live memories only
    live_hits = store.search(
        query_embedding,
        k=k,
        min_similarity=min_similarity,
        origin="live",
    )

    # If we already have k live memories, return them
    if len(live_hits) >= k:
        return live_hits[:k]

    # Otherwise, fetch bootstrap to fill remaining slots
    remaining = k - len(live_hits)
    bootstrap_hits = store.search(
        query_embedding,
        k=remaining,
        min_similarity=min_similarity,
        origin="bootstrap",
    )

    # Combine live + bootstrap, maintaining order
    # Live memories always come first, even if bootstrap has slightly higher sim
    return live_hits + bootstrap_hits


def _format_hits(
    hits: "list[tuple[Any, float]]",
    max_tokens: int,
) -> str:
    """
    Format memory hits into a readable context string.

    Format per hit:
        "- <sim:0.XX> [live/bootstrap] content_preview"

    Total output capped at max_tokens (~4 chars per token).
    """
    if not hits:
        return ""

    parts = []
    total_chars = 0
    char_budget = max_tokens * 4

    for mem, sim in hits:
        # Preview content, truncate to ~150 chars
        content_preview = mem.content[:150].strip()
        origin_tag = f"[{mem.origin}]" if mem.origin else ""

        part = f"- <sim:{sim:.2f}> {origin_tag} {content_preview}"
        parts.append(part)
        total_chars += len(part) + 2  # +2 for newline separation

        if total_chars >= char_budget:
            break

    body = "\n".join(parts)
    prefix = "[Past session notes — retrieved from memory]\n"
    return prefix + body


def recall(reasoning: str, k: int = 3) -> "str | None":
    """
    Embed reasoning, search episodic memory, return a formatted context string.

    Legacy entry point — delegates to recall_context() for backwards compatibility.

    Returns None when:
    - sentence_transformers is not installed (embed returns None)
    - vector store has no rows or top similarity is below RECALL_SIM_THRESHOLD
    - any exception occurs (caught broadly — must not propagate into re_cur)

    Output format per hit:
        "<sim:0.42> content[:200]"
    Prefixed with "[Recalled context] " and total length capped at 500 chars.
    """
    result = recall_context({"reasoning": reasoning}, k=k)
    if result is None:
        return None

    # Backwards-compat: truncate to 500 chars for old callers
    if len(result) > 500:
        result = result[:500]

    # Replace new prefix with old one for exact backwards compat
    if result.startswith("[Past session notes"):
        result = "[Recalled context] " + result[len("[Past session notes — retrieved from memory]\n"):]

    return result


def recall_context(context: dict, k: int = 3, store: "Any | None" = None) -> "str | None":
    """
    Embed richer context, search episodic memory with live-origin preference.

    Context dict keys (all optional, at least one required):
        - "reasoning": LLM's reasoning text (primary signal)
        - "user_message": Last user message content
        - "last_actions": Summary of recent tool calls/results

    Args:
        context: Dict with reasoning, user_message, and/or last_actions
        k: Maximum number of results to return
        store: Optional VectorStore instance (for testing)

    Returns formatted context string or None on any failure.
    Never propagates exceptions — all errors return None.

    Output format per hit:
        "- <sim:0.XX> [live/bootstrap] content_preview"
    Prefixed with "[Past session notes — retrieved from memory]" and capped
    at ~RECALL_MAX_TOKENS tokens (default 2000).
    """
    try:
        # Build search text from context components
        search_parts = []

        reasoning = context.get("reasoning", "")
        if reasoning:
            search_parts.append(f"Reasoning: {reasoning}")

        user_msg = context.get("user_message", "")
        if user_msg:
            search_parts.append(f"User message: {user_msg}")

        last_actions = context.get("last_actions", "")
        if last_actions:
            search_parts.append(f"Recent actions: {last_actions}")

        if not search_parts:
            # Fallback: try to use any non-empty value
            for v in context.values():
                if v and isinstance(v, str):
                    search_parts.append(v)
                    break

        if not search_parts:
            return None

        search_text = " ".join(search_parts)

        # Deferred heavy imports
        from memory.embed import embed

        vec = embed(search_text)
        if vec is None:
            return None

        # Search with live-origin preference
        hits = _search_with_live_preference(
            vec,
            k=k,
            min_similarity=RECALL_SIM_THRESHOLD,
            store=store,
        )

        if not hits:
            return None

        return _format_hits(hits, max_tokens=RECALL_MAX_TOKENS)

    except Exception:
        logger.exception("recall_context() failed — returning None")
        return None
