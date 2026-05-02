"""
Ingest past session chats into the episodic memory store.
Walks eval_results/chats/run1_*_messages.json, extracts adjacent
(assistant_with_reasoning, tool_response) pairs, embeds, and inserts.

Session_id: basename of the messages file stripped of '_messages.json'
            e.g. 'run1_1776674733'
Idempotent: INSERT OR IGNORE on (session_id, timestamp).
"""
import glob
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Resolve paths relative to this file
_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT_CORE = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_AGENT_CORE)
_CHATS_GLOB = os.path.join(_REPO_ROOT, "eval_results", "chats", "run1_*_messages.json")

ASSISTANT_ROLES = {"assistant", "self", "entity"}


def _extract_pairs(messages: list) -> list:
    """
    Walk messages list and yield dicts with keys:
      reasoning_text, action_json, observation_text, timestamp
    for each adjacent (assistant_with_reasoning_and_tool_calls, tool_response) pair.
    Skips assistant turns without a 'reasoning' field.
    """
    pairs = []
    for i, msg in enumerate(messages):
        if msg.get("role") not in ASSISTANT_ROLES:
            continue
        reasoning = msg.get("reasoning", "")
        if not reasoning:
            continue
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue
        # Look for the immediately following tool response
        if i + 1 >= len(messages):
            continue
        nxt = messages[i + 1]
        if nxt.get("role") != "tool":
            continue
        action_json = json.dumps(tool_calls)
        observation_text = nxt.get("content", "")
        if isinstance(observation_text, list):
            # some tool responses store content as list of parts
            observation_text = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in observation_text
            )
        pairs.append({
            "reasoning_text": reasoning,
            "action_json": action_json,
            "observation_text": str(observation_text),
            "timestamp": msg.get("timestamp", ""),
        })
    return pairs


def ingest_file(path: str, store, embed_fn) -> int:
    """
    Ingest one messages.json file. Returns number of new records inserted
    (duplicates silently skipped by vector_store).
    """
    from memory.vector_store import Record

    session_id = os.path.basename(path).replace("_messages.json", "")
    with open(path, "r", encoding="utf-8") as f:
        messages = json.load(f)

    pairs = _extract_pairs(messages)
    inserted = 0
    for p in pairs:
        vec = embed_fn(p["reasoning_text"])
        rec = Record(
            session_id=session_id,
            timestamp=p["timestamp"],
            reasoning_text=p["reasoning_text"],
            action_json=p["action_json"],
            observation_text=p["observation_text"],
            embedding=vec,  # may be None if sentence_transformers unavailable
        )
        store.insert(rec)
        inserted += 1
    return inserted


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from memory.embed import embed
    from memory.vector_store import get_store

    store = get_store()
    files = sorted(glob.glob(_CHATS_GLOB))
    if not files:
        logger.warning("No run1_*_messages.json files found under %s", _CHATS_GLOB)
        return

    total = 0
    for path in files:
        n = ingest_file(path, store, embed)
        logger.info("  %s: %d pairs", os.path.basename(path), n)
        total += n
    logger.info("Ingestion complete. Total pairs processed: %d", total)
    store.close()


if __name__ == "__main__":
    main()
