#!/usr/bin/env python3
"""
Phase 3 validation script.

Tests:
1. recall_context() with richer context (user_message + last_actions)
2. Live-origin preference over bootstrap (never let bootstrap displace live)
3. Context budget token estimation
4. Backwards compatibility of recall() entry point

Usage: python agent-core/memory/test_phase3.py (from project root)
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
)


def test_live_origin_preference():
    """Test that live memories are preferred over bootstrap at equal similarity."""
    print("[1] Testing live-origin preference...")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        store = VectorStore(db_path)

        # Create test memories with identical embeddings (same similarity)
        base_vec = [0.1] * 384

        # Add bootstrap memories first
        for i in range(5):
            mem = Memory(
                content=f"Bootstrap memory {i}",
                embedding=base_vec,
                metadata={"source": "bootstrap"},
                created_at="2026-05-10T00:00:00Z",
                origin="bootstrap",
                validated=True,
            )
            store.add(mem)

        # Add live memories
        for i in range(3):
            mem = Memory(
                content=f"Live memory {i}",
                embedding=base_vec,
                metadata={"source": "live"},
                created_at="2026-05-10T01:00:00Z",
                origin="live",
                validated=True,
            )
            store.add(mem)

        print(f"  ✓ Added 5 bootstrap + 3 live memories")

        # Import after populating store
        from memory.recall import _search_with_live_preference

        # Search for top 5 (pass store explicitly for test isolation)
        results = _search_with_live_preference(
            base_vec,
            k=5,
            min_similarity=0.0,
            store=store,
        )

        # Should get all 3 live memories first, then 2 bootstrap
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"

        # Check that live memories come first
        live_results = [r for r in results if r[0].origin == "live"]
        bootstrap_results = [r for r in results if r[0].origin == "bootstrap"]

        assert len(live_results) == 3, f"Expected 3 live results, got {len(live_results)}"
        assert len(bootstrap_results) == 2, f"Expected 2 bootstrap results, got {len(bootstrap_results)}"

        # Verify live results appear before bootstrap in the list
        live_indices = [i for i, (mem, _) in enumerate(results) if mem.origin == "live"]
        bootstrap_indices = [i for i, (mem, _) in enumerate(results) if mem.origin == "bootstrap"]
        assert max(live_indices) < min(bootstrap_indices), "Live memories should come before bootstrap"

        print(f"  ✓ Live memories ({len(live_results)}) ranked before bootstrap ({len(bootstrap_results)})")
        print("    PASSED\n")


def test_recall_context_rich_input():
    """Test recall_context with user_message and last_actions."""
    print("[2] Testing recall_context with rich input...")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        store = VectorStore(db_path)

        # Add a memory about terminal commands
        vec = embed("Used terminal to run ls command")
        if vec is None:
            print("  ⚠ sentence-transformers not installed, skipping")
            return False

        mem = Memory(
            content="Executed: ls -la -> showed README.md and workspace/",
            embedding=vec,
            metadata={"tool": "terminal"},
            created_at="2026-05-10T00:00:00Z",
            origin="live",
            validated=True,
        )
        store.add(mem)

        # Import recall_context
        from memory.recall import recall_context

        # Test with just reasoning (backwards compat)
        result = recall_context({"reasoning": "what happened with ls"}, store=store)
        assert result is not None, "recall_context should find memory with reasoning only"
        assert "ls" in result.lower() or "terminal" in result.lower()
        print(f"  ✓ Found memory with reasoning only")

        # Test with richer context
        result = recall_context({
            "reasoning": "I need to check previous commands",
            "user_message": "What did I do earlier?",
            "last_actions": "terminal: listing files",
        }, store=store)
        assert result is not None, "recall_context should work with rich context"
        print(f"  ✓ Found memory with rich context")

        # Test with empty context
        result = recall_context({}, store=store)
        assert result is None, "recall_context should return None for empty context"
        print(f"  ✓ Returns None for empty context")

        print("    PASSED\n")
        return True


def test_context_budget():
    """Test that context output respects token budget."""
    print("[3] Testing context budget...")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        store = VectorStore(db_path)

        vec = embed("test memory")
        if vec is None:
            print("  ⚠ sentence-transformers not installed, skipping")
            return False

        # Add many memories (each ~200 chars content)
        for i in range(20):
            mem = Memory(
                content=f"Memory {i}: " + "x" * 200,  # Long content
                embedding=vec,
                metadata={"index": i},
                created_at="2026-05-10T00:00:00Z",
                origin="live",
                validated=True,
            )
            store.add(mem)

        from memory.recall import recall_context, _estimate_tokens, RECALL_MAX_TOKENS

        result = recall_context({"reasoning": "test"}, k=20, store=store)
        assert result is not None, "Should return results"

        # Check estimated tokens is within budget
        estimated = _estimate_tokens(result)
        # Allow some overhead for prefix
        assert estimated <= RECALL_MAX_TOKENS + 100, f"Estimated tokens {estimated} exceeds budget {RECALL_MAX_TOKENS}"

        print(f"  ✓ Output respects budget: ~{estimated} tokens (max {RECALL_MAX_TOKENS})")
        print("    PASSED\n")
        return True


def test_recall_backwards_compat():
    """Test that recall() still works as a thin wrapper."""
    print("[4] Testing recall() backwards compatibility...")

    vec = embed("test memory for compat")
    if vec is None:
        print("  ⚠ sentence-transformers not installed, skipping")
        return False

    # Use the default store path for this test (since recall() uses singleton)
    from memory.vector_store import DEFAULT_DB_PATH, _default_store
    import os

    # Create the state directory if it doesn't exist
    os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)

    # Reset the singleton to force a fresh store
    import memory.vector_store as vs_module
    vs_module._default_store = None

    store = VectorStore(DEFAULT_DB_PATH)

    mem = Memory(
        content="Test memory content for compat check",
        embedding=vec,
        metadata={},
        created_at="2026-05-10T00:00:00Z",
        origin="live",
        validated=True,
    )
    store.add(mem)

    from memory.recall import recall

    result = recall("test memory")
    assert result is not None, "recall() should work"
    assert "[Recalled context]" in result, "Should use old prefix"
    assert len(result) <= 500, "Should be capped at 500 chars"

    print(f"  ✓ recall() works with old format (len={len(result)})")
    print("    PASSED\n")
    return True


def test_live_vs_bootstrap_equal_similarity():
    """Test that bootstrap never displaces live at equal similarity."""
    print("[5] Testing bootstrap never displaces live...")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        store = VectorStore(db_path)

        # Create memories with VERY similar content (same vector)
        vec = [0.5] * 384

        # Add 2 bootstrap, then 2 live (all with same similarity)
        for i in range(2):
            store.add(Memory(
                content=f"Bootstrap task {i}",
                embedding=vec,
                metadata={},
                created_at="2026-05-10T00:00:00Z",
                origin="bootstrap",
                validated=True,
            ))

        for i in range(2):
            store.add(Memory(
                content=f"Live task {i}",
                embedding=vec,
                metadata={},
                created_at="2026-05-10T01:00:00Z",
                origin="live",
                validated=True,
            ))

        from memory.recall import _search_with_live_preference

        # Search for k=3 (pass store explicitly)
        results = _search_with_live_preference(vec, k=3, min_similarity=0.0, store=store)

        # Should get: 2 live + 1 bootstrap (not the other way around)
        assert len(results) == 3
        live_count = sum(1 for mem, _ in results if mem.origin == "live")
        bootstrap_count = sum(1 for mem, _ in results if mem.origin == "bootstrap")

        assert live_count == 2, f"Expected 2 live results, got {live_count}"
        assert bootstrap_count == 1, f"Expected 1 bootstrap result, got {bootstrap_count}"

        # Live should come first
        assert results[0][0].origin == "live"
        assert results[1][0].origin == "live"
        assert results[2][0].origin == "bootstrap"

        print(f"  ✓ Live memories rank first despite equal similarity")
        print("    PASSED\n")


def main():
    print("=" * 50)
    print("Phase 3 Validation: Runtime Memory Retrieval")
    print("=" * 50)
    print()

    has_embeddings = True

    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        has_embeddings = False
        print("⚠ sentence-transformers not installed")
        print("  Install with: pip install sentence-transformers")
        print()

    test_live_origin_preference()
    test_live_vs_bootstrap_equal_similarity()

    if has_embeddings:
        test_recall_context_rich_input()
        test_context_budget()
        test_recall_backwards_compat()

    print("=" * 50)
    print("Phase 3 validation complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
