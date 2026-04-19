"""re_scribe — Episodic memory compressor for crash recovery."""

import logging
import re_lay

logger = logging.getLogger("re_scribe")

SCRIBE_SYSTEM = (
    "You are a memory compression module. Given a crash log, produce a "
    "first-person summary in under 80 tokens covering: (1) what I was trying "
    "to do, (2) what blocked me, (3) what I should try differently next session. "
    "Use past tense. Reference specific filenames and error types. No markdown."
)


def compress(raw_context, base_url=None):
    """Compress raw crash context into a short first-person episodic memory.
    
    Args:
        raw_context: str — verbose crash log / environmental state text
        base_url: optional LLM endpoint override
    
    Returns:
        str — compressed narrative, or a fallback summary on failure
    """
    if not raw_context or not raw_context.strip():
        return "I have no memory of my previous session."

    # Truncate input to prevent exceeding context limits on the scribe call itself
    truncated = raw_context[:8000]

    messages = [
        {"role": "system", "content": SCRIBE_SYSTEM},
        {"role": "user", "content": truncated},
    ]

    result = re_lay.send(messages, base_url=base_url, max_tokens=100, tools=None)

    if result.get("error"):
        logger.warning("Scribe LLM call failed: %s — using fallback", result["error"])
        # Fallback: extract first meaningful line from the crash context
        lines = [l.strip() for l in raw_context.split("\n") if l.strip()]
        summary = lines[0][:200] if lines else "Unknown crash."
        return f"I crashed in my previous session. Context: {summary}"

    content = (result.get("content") or "").strip()
    if not content:
        return "I crashed in my previous session but could not reconstruct what happened."

    return content
