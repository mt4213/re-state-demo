#!/usr/bin/env python3
"""
Phase 4 validation script.

Tests:
1. Parsing synthetic JSONL logs
2. Deterministic metadata extraction (tools, files, counts)
3. Final state classification
4. Idempotent re-runs of sleep_cycle
5. SummaryEntry serialization

Usage: python agent-core/memory/test_phase4.py (from project root)
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add agent-core to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.summarize import (
    SummaryEntry,
    summarize_session,
    _load_jsonl,
    _extract_files_from_command,
    _determine_final_state,
    _extract_deterministic_metadata,
)
from memory.sleep_cycle import run_sleep_cycle


# Synthetic session log for testing
_SYNTHETIC_JSONL = """{"timestamp": "2026-05-10T10:00:00Z", "session_id": "test_session_1", "type": "session_start", "system_prompt_preview": "Test prompt"}
{"timestamp": "2026-05-10T10:00:05Z", "session_id": "test_session_1", "type": "tool_call", "tool": "terminal", "input": {"command": "ls -la"}, "output": "total 4\\ndrwxr-xr-x 2 user user 4096 May 10 10:00 .", "duration_ms": 50, "exit_code": 0}
{"timestamp": "2026-05-10T10:00:10Z", "session_id": "test_session_1", "type": "tool_call", "tool": "file_read", "input": {"path": "agent-core/re_cur.py"}, "output": "Content of re_cur.py", "duration_ms": 20, "exit_code": 0}
{"timestamp": "2026-05-10T10:00:15Z", "session_id": "test_session_1", "type": "tool_call", "tool": "file_write", "input": {"path": "workspace/test.txt"}, "output": "Wrote 100 bytes", "duration_ms": 30, "exit_code": 0}
{"timestamp": "2026-05-10T10:00:20Z", "session_id": "test_session_1", "type": "error", "error_type": "test_error", "message": "Test error message"}
{"timestamp": "2026-05-10T10:00:25Z", "session_id": "test_session_1", "type": "llm_response", "turn": 1, "tool_names": ["terminal", "file_read"]}
{"timestamp": "2026-05-10T10:00:30Z", "session_id": "test_session_1", "type": "session_end", "exit_reason": "natural", "total_turns": 5, "exit_code": 0}"""


def test_load_jsonl():
    """Test loading and parsing JSONL files."""
    print("[1] Testing JSONL parsing...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        events = _load_jsonl(temp_path)
        assert len(events) == 7, f"Expected 7 events, got {len(events)}"
        assert events[0]["type"] == "session_start"
        assert events[-1]["type"] == "session_end"
        print(f"  ✓ Parsed {len(events)} events correctly")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_extract_files_from_command():
    """Test file extraction from shell commands."""
    print("[2] Testing file extraction from commands...")

    tests = [
        ("cat agent-core/re_cur.py", ["agent-core/re_cur.py"], True),
        ("ls -la workspace/", ["workspace/"], True),
        ("vim agent-core/tools/execute.py", ["agent-core/tools/execute.py"], True),
        ("grep pattern file.txt", [], False),  # grep not in file_cmds list
        ("rm file.py", ["file.py"], True),
    ]

    for cmd, expected_files, should_match in tests:
        result = _extract_files_from_command(cmd)
        # Check if any expected file is in the result
        has_match = any(exp in result for exp in expected_files)
        if should_match:
            assert has_match, f"Failed for '{cmd}': expected one of {expected_files}, got {result}"
        else:
            assert not has_match, f"Failed for '{cmd}': expected no matches, got {result}"

    print(f"  ✓ File extraction works correctly")
    print("    PASSED\n")


def test_deterministic_metadata_extraction():
    """Test extraction of deterministic metadata from events."""
    print("[3] Testing deterministic metadata extraction...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        events = _load_jsonl(temp_path)
        metadata = _extract_deterministic_metadata(events)

        # Check tool counts
        assert metadata["n_tool_calls"] == 3, f"Expected 3 tool calls, got {metadata['n_tool_calls']}"
        assert metadata["n_errors"] == 1, f"Expected 1 error, got {metadata['n_errors']}"

        # Check tools_used
        assert "terminal" in metadata["tools_used"]
        assert "file_read" in metadata["tools_used"]
        assert "file_write" in metadata["tools_used"]

        # Check files_touched
        assert "agent-core/re_cur.py" in metadata["files_touched"]
        assert "workspace/test.txt" in metadata["files_touched"]

        # Check final state
        assert metadata["final_state"] == "working", f"Expected 'working', got {metadata['final_state']}"

        print(f"  ✓ Metadata extracted correctly:")
        print(f"    - Tool calls: {metadata['n_tool_calls']}")
        print(f"    - Errors: {metadata['n_errors']}")
        print(f"    - Tools: {metadata['tools_used']}")
        print(f"    - Files: {metadata['files_touched']}")
        print(f"    - Final state: {metadata['final_state']}")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_final_state_classification():
    """Test final state classification from different exit conditions."""
    print("[4] Testing final state classification...")

    # Test working state
    events_working = [
        {"type": "session_end", "exit_reason": "natural", "exit_code": 0}
    ]
    assert _determine_final_state(events_working) == "working"

    # Test broken state (circuit breaker)
    events_broken = [
        {"type": "session_end", "exit_reason": "circuit_breaker", "exit_code": 1}
    ]
    assert _determine_final_state(events_broken) == "broken"

    # Test broken state (error)
    events_error = [
        {"type": "session_end", "exit_reason": "error", "exit_code": 1}
    ]
    assert _determine_final_state(events_error) == "broken"

    # Test in_progress (no session_end)
    events_incomplete = [
        {"type": "tool_call", "tool": "terminal"}
    ]
    assert _determine_final_state(events_incomplete) == "in_progress"

    print(f"  ✓ Final state classification works correctly")
    print("    PASSED\n")


def test_summary_entry_serialization():
    """Test SummaryEntry to_dict serialization."""
    print("[5] Testing SummaryEntry serialization...")

    entry = SummaryEntry(
        content="Test summary content",
        metadata={"key": "value"},
        session_id="test_session",
        started_at="2026-05-10T10:00:00Z",
        ended_at="2026-05-10T10:01:00Z",
        tools_used={"terminal": 2, "file_read": 1},
        files_touched=["file1.py", "file2.py"],
        n_tool_calls=3,
        n_errors=0,
        final_state="working",
        source_log_path="/path/to/log.jsonl",
    )

    d = entry.to_dict()
    assert d["content"] == "Test summary content"
    assert d["session_id"] == "test_session"
    assert d["tools_used"]["terminal"] == 2
    assert d["final_state"] == "working"

    print(f"  ✓ SummaryEntry serialization works")
    print("    PASSED\n")


def test_idempotent_sleep_cycle():
    """Test that sleep cycle skips already-summarized sessions."""
    print("[6] Testing idempotent sleep cycle...")

    with tempfile.TemporaryDirectory() as tmpdir:
        chats_dir = Path(tmpdir)

        # Create two synthetic JSONL files
        jsonl_1 = chats_dir / "sealed_audit_001.jsonl"
        jsonl_2 = chats_dir / "sealed_audit_002.jsonl"

        jsonl_1.write_text(_SYNTHETIC_JSONL)
        jsonl_2.write_text(_SYNTHETIC_JSONL)

        # First run: both should be summarized (dry-run mode)
        stats1 = run_sleep_cycle(chats_dir=chats_dir, dry_run=True)
        assert stats1["newly_summarized"] == 2, f"Expected 2 new, got {stats1['newly_summarized']}"
        assert stats1["already_summarized"] == 0

        # Write one summary file manually
        summary_1 = chats_dir / "sealed_audit_001.summary.json"
        summary_1.write_text(json.dumps({"test": "summary"}))

        # Second run: only one should be new
        stats2 = run_sleep_cycle(chats_dir=chats_dir, dry_run=True)
        assert stats2["already_summarized"] == 1, f"Expected 1 already summarized, got {stats2['already_summarized']}"
        assert stats2["newly_summarized"] == 1, f"Expected 1 new, got {stats2['newly_summarized']}"

        print(f"  ✓ Idempotency works correctly")
        print("    PASSED\n")


def test_summarize_session_fallback():
    """Test summarize_session with LLM failure (uses fallback)."""
    print("[7] Testing summarize_session fallback...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        # This will fail to connect to LLM (no server running)
        # and should fall back to deterministic summary
        summary = summarize_session(temp_path)

        assert summary is not None, "summarize_session should return something (fallback)"
        assert summary.session_id == "test_session_1"
        assert summary.final_state == "working"
        assert summary.n_tool_calls == 3
        assert summary.n_errors == 1
        assert "tool calls" in summary.content.lower() or "session" in summary.content.lower()

        print(f"  ✓ Fallback summary generated correctly")
        print(f"    Content: {summary.content[:100]}...")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_broken_final_state():
    """Test that broken sessions are correctly classified."""
    print("[8] Testing broken final state detection...")

    broken_jsonl = """{"timestamp": "2026-05-10T10:00:00Z", "session_id": "broken_session", "type": "session_start", "system_prompt_preview": "Test"}
{"timestamp": "2026-05-10T10:00:05Z", "session_id": "broken_session", "type": "error", "error_type": "circuit_breaker", "message": "Too many failures"}
{"timestamp": "2026-05-10T10:00:10Z", "session_id": "broken_session", "type": "session_end", "exit_reason": "circuit_breaker", "total_turns": 2, "exit_code": 1}"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(broken_jsonl)
        temp_path = Path(f.name)

    try:
        summary = summarize_session(temp_path)
        assert summary is not None
        assert summary.final_state == "broken", f"Expected 'broken', got {summary.final_state}"
        print(f"  ✓ Broken state correctly detected")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def main():
    print("=" * 50)
    print("Phase 4 Validation: Sleep-Cycle Summarization")
    print("=" * 50)
    print()

    test_load_jsonl()
    test_extract_files_from_command()
    test_deterministic_metadata_extraction()
    test_final_state_classification()
    test_summary_entry_serialization()
    test_idempotent_sleep_cycle()
    test_summarize_session_fallback()
    test_broken_final_state()

    print("=" * 50)
    print("Phase 4 validation complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
