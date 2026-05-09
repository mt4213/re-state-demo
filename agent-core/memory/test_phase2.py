#!/usr/bin/env python3
"""
Phase 2 validation script.

Tests:
1. VectorStore schema creation and CRUD
2. Embedding generation
3. Cosine similarity search
4. Audit log ingestion

Usage: python agent-core/memory/test_phase2.py (from project root)
"""
import os
import sys
import tempfile
from pathlib import Path

# Add agent-core to path so "from memory import ..." works
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory import (
    VectorStore,
    Memory,
    embed,
    ingest_audit_log,
    cosine_similarity,
    get_store,
)


def test_vector_store_basic():
    """Test basic VectorStore operations."""
    print("[1] Testing VectorStore basic operations...")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        store = VectorStore(db_path)

        # Add test memories
        mem1 = Memory(
            content="Used terminal to run ls command",
            embedding=[0.1] * 384,
            metadata={"tool": "terminal", "command": "ls"},
            created_at="2026-05-10T00:00:00Z",
            origin="live",
            validated=True,
        )
        id1 = store.add(mem1)
        assert id1 > 0, "Failed to add memory"

        # Retrieve
        retrieved = store.get(id1)
        assert retrieved is not None, "Failed to retrieve memory"
        assert retrieved.content == mem1.content

        # Count
        assert store.count() == 1

        # Stats
        stats = store.stats()
        assert stats["total"] == 1
        assert stats["live"] == 1

        print("  ✓ CRUD operations work")

        # Test search
        results = store.search([0.1] * 384, k=5)
        assert len(results) == 1
        assert results[0][0].id == id1
        assert results[0][1] > 0.9  # High similarity for identical vectors

        print("  ✓ Similarity search works")

        store.close()
    print("    PASSED\n")


def test_embedding():
    """Test embedding generation."""
    print("[2] Testing embedding generation...")

    vec = embed("test query about running commands")
    if vec is None:
        print("  ⚠ sentence-transformers not installed, skipping embedding test")
        print("    Install with: pip install sentence-transformers")
        return False

    assert len(vec) == 384, f"Expected 384-dim vector, got {len(vec)}"
    assert all(isinstance(x, (int, float)) for x in vec)

    print(f"  ✓ Generated {len(vec)}-dim embedding")
    print("    PASSED\n")
    return True


def test_cosine_similarity():
    """Test cosine similarity calculation."""
    print("[3] Testing cosine similarity...")

    import numpy as np

    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])  # Identical
    c = np.array([0.0, 1.0, 0.0])  # Orthogonal

    sim_ab = cosine_similarity(a, b)
    sim_ac = cosine_similarity(a, c)

    assert sim_ab > 0.99, f"Identical vectors should have high similarity: {sim_ab}"
    assert sim_ac < 0.1, f"Orthogonal vectors should have low similarity: {sim_ac}"

    print(f"  ✓ Identical vectors: {sim_ab:.4f}")
    print(f"  ✓ Orthogonal vectors: {sim_ac:.4f}")
    print("    PASSED\n")


def test_ingest_audit_log():
    """Test audit log ingestion."""
    print("[4] Testing audit log ingestion...")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake audit log
        audit_path = Path(tmpdir) / "test_audit.jsonl"
        with open(audit_path, "w") as f:
            f.write('{"type":"session_start","session_id":"sess_test","timestamp":"2026-05-10T00:00:00Z"}\n')
            f.write('{"type":"tool_call","session_id":"sess_test","timestamp":"2026-05-10T00:00:01Z","tool":"terminal","input":{"command":"ls -la"},"output":"total 0","exit_code":0,"duration_ms":10}\n')
            f.write('{"type":"tool_call","session_id":"sess_test","timestamp":"2026-05-10T00:00:02Z","tool":"file_read","input":{"path":"README.md"},"output":"# README","exit_code":0,"duration_ms":5}\n')

        # Use a separate store for this test
        db_path = Path(tmpdir) / "test_ingest.sqlite"
        from memory.vector_store import DEFAULT_DB_PATH

        # Temporarily override default path
        original_path = DEFAULT_DB_PATH
        import memory.vector_store as vs_module
        vs_module.DEFAULT_DB_PATH = db_path

        try:
            # Import fresh to get new default path
            import importlib
            import memory.ingest_memory as im
            importlib.reload(im)

            # Ingest
            count = im.ingest_audit_log(audit_path, origin="live")
            assert count == 2, f"Expected 2 memories, got {count}"

            print(f"  ✓ Ingested {count} tool_call events")

            # Verify store contents
            store = VectorStore(db_path)
            stats = store.stats()
            assert stats["total"] == 2, f"Expected 2 memories in store, got {stats['total']}"
            assert stats["live"] == 2

            print(f"  ✓ Store contains {stats['total']} memories")
            print("    PASSED\n")

        finally:
            vs_module.DEFAULT_DB_PATH = original_path


def test_phase1_existing():
    """Test with existing Phase 1 audit log if available."""
    print("[5] Testing with existing Phase 1 audit log...")

    audit_files = list(Path("eval_results/chats").glob("*_sealed_audit.jsonl"))
    if not audit_files:
        print("  ⚠ No Phase 1 audit logs found in eval_results/chats/")
        print("    Run ./run_experiment.sh first to generate audit logs")
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_live.sqlite"

        # Create a store with explicit path
        store = VectorStore(db_path)

        # Manually ingest into this store
        import json
        from datetime import datetime, timezone

        count = 0
        with open(audit_files[0]) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") != "tool_call":
                    continue

                session_id = event.get("session_id")
                if not session_id:
                    continue

                # Create summary
                tool = event["tool"]
                input_data = event.get("input", {})
                output = event.get("output", "")

                if tool == "terminal":
                    content = f"Executed: {input_data.get('command', '')[:200]} -> {output[:200]}"
                elif tool == "file_read":
                    content = f"Read file: {input_data.get('path', '')}"
                elif tool == "file_write":
                    content = f"Wrote file: {input_data.get('path', '')} - {(output or '')[:100]}"
                else:
                    content = f"{tool}: {str(input_data)[:200]}"

                # Embed
                vec = embed(content)
                if vec is None:
                    continue

                metadata = {
                    "session_id": session_id,
                    "tool": tool,
                    "timestamp": event["timestamp"],
                }

                memory = Memory(
                    content=content,
                    embedding=vec,
                    metadata=metadata,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    origin="live",
                    validated=False,  # Live sessions need Phase 5 validation
                )

                store.add(memory)
                count += 1

        print(f"  ✓ Ingested {count} memories from {audit_files[0].name}")

        stats = store.stats()
        print(f"  ✓ Store stats: {stats}")

        # Test search
        vec = embed("terminal command")
        if vec:
            results = store.search(vec, k=3)
            print(f"  ✓ Search for 'terminal command' returned {len(results)} results")
            if results:
                print(f"    Top result: {results[0][0].content[:80]}...")

        print("    PASSED\n")
        return True


def main():
    print("=" * 50)
    print("Phase 2 Validation: Vector Store + Embedding")
    print("=" * 50)
    print()

    has_embeddings = test_embedding()

    test_vector_store_basic()
    test_cosine_similarity()
    test_ingest_audit_log()

    if has_embeddings:
        test_phase1_existing()

    print("=" * 50)
    print("Phase 2 validation complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
