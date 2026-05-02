"""
Lazy singleton embedding function using sentence-transformers/all-MiniLM-L6-v2.
Returns None (and logs a one-time warning) if sentence_transformers is unavailable.
"""
import logging

logger = logging.getLogger(__name__)

_model = None
_warned = False
_available = None  # None = not yet probed


def _probe():
    global _available
    if _available is not None:
        return _available
    try:
        import sentence_transformers  # noqa: F401
        _available = True
    except ImportError:
        _available = False
    return _available


def embed(text: str):
    """
    Embed text using all-MiniLM-L6-v2.
    Returns list[float] (384-d) or None if sentence_transformers is not installed.
    """
    global _model, _warned

    if not _probe():
        if not _warned:
            logger.warning(
                "sentence_transformers not installed — embed() will return None. "
                "Install sentence-transformers>=2.5 to enable implicit memory."
            )
            _warned = True
        return None

    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")

    vec = _model.encode(text, normalize_embeddings=True)
    return vec.tolist()
