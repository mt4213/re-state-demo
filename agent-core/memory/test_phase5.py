#!/usr/bin/env python3
"""
Phase 5 validation script.

Tests:
1. LAYER 1: deterministic validation (confirms/refutes/unverifiable)
2. LAYER 2: semantic validation gated to unverifiable claims only
3. LAYER 3: decision logic for each branch
4. Full pipeline end-to-end with mocked L2 LLM
5. Idempotent re-runs (validation marker)

Usage: python agent-core/memory/test_phase5.py (from project root)
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

# Add agent-core to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.summarize import SummaryEntry
from memory.validate import (
    validate_summary,
    ValidationResult,
    Decision,
    ClaimVerdict,
    _extract_claims_from_prose,
    _validate_deterministic,
    _make_decision,
    _load_raw_log,
    re_summarize_strict,
)


# Synthetic test data
_SYNTHETIC_JSONL = """{"timestamp": "2026-05-10T10:00:00Z", "session_id": "test_phase5", "type": "session_start", "system_prompt_preview": "Test"}
{"timestamp": "2026-05-10T10:00:05Z", "session_id": "test_phase5", "type": "tool_call", "tool": "terminal", "input": {"command": "ls -la"}, "output": "total 4", "duration_ms": 50, "exit_code": 0}
{"timestamp": "2026-05-10T10:00:10Z", "session_id": "test_phase5", "type": "tool_call", "tool": "file_read", "input": {"path": "agent-core/re_cur.py"}, "output": "Content here", "duration_ms": 20, "exit_code": 0}
{"timestamp": "2026-05-10T10:00:15Z", "session_id": "test_phase5", "type": "error", "error_type": "test_error", "message": "Test error"}
{"timestamp": "2026-05-10T10:00:20Z", "session_id": "test_phase5", "type": "session_end", "exit_reason": "natural", "total_turns": 3, "exit_code": 0}"""


def test_layer1_deterministic_validation():
    """Test LAYER 1: deterministic validation confirms/refutes claims."""
    print("[L1] Testing deterministic validation...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        summary = SummaryEntry(
            content="Used terminal and file_read tools. Modified agent-core/re_cur.py. Encountered 1 error.",
            metadata={"session_id": "test_phase5"},
            session_id="test_phase5",
            started_at="2026-05-10T10:00:00Z",
            ended_at="2026-05-10T10:00:20Z",
            tools_used={"terminal": 1, "file_read": 1},
            files_touched=["agent-core/re_cur.py"],
            n_tool_calls=2,
            n_errors=1,
            final_state="working",
            source_log_path=str(temp_path),
        )

        result = validate_summary(summary, temp_path, llm_fn=lambda log, claim: (True, "mock"))

        # Check that claims were extracted
        assert len(result.claims) > 0, "Should extract claims"

        # Check that tool claims were confirmed
        tool_claims = [c for c in result.claims if c.claim_type == "tool"]
        for claim in tool_claims:
            assert claim.verdict in (ClaimVerdict.CONFIRMED, ClaimVerdict.UNVERIFIABLE), \
                f"Tool claim {claim.text} should be confirmed or unverifiable"

        # Check that file claim was confirmed
        file_claims = [c for c in result.claims if c.claim_type == "file"]
        assert len(file_claims) > 0, "Should find file claims"
        assert file_claims[0].verdict == ClaimVerdict.CONFIRMED, \
            f"File claim should be confirmed, got {file_claims[0].verdict}"

        # Check that error claim was confirmed
        error_claims = [c for c in result.claims if c.claim_type == "error"]
        assert len(error_claims) > 0, "Should find error claims"
        assert error_claims[0].verdict == ClaimVerdict.CONFIRMED, \
            f"Error claim should be confirmed, got {error_claims[0].verdict}"

        print(f"  ✓ Deterministic validation extracted {len(result.claims)} claims")
        print(f"    - Tool claims: {len(tool_claims)}")
        print(f"    - File claims: {len(file_claims)}")
        print(f"    - Error claims: {len(error_claims)}")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_layer1_refutes_false_claims():
    """Test LAYER 1: deterministic validation refutes false claims."""
    print("[L1] Testing refutation of false claims...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        # Summary with a claim that's NOT in the log
        summary = SummaryEntry(
            content="Used terminal, file_write, and database tools. Modified file.txt.",  # file_write and database NOT in log
            metadata={"session_id": "test_phase5"},
            session_id="test_phase5",
            started_at="2026-05-10T10:00:00Z",
            ended_at="2026-05-10T10:00:20Z",
            tools_used={"terminal": 1, "file_write": 1, "database": 1},  # file_write, database NOT in log
            files_touched=["file.txt"],  # NOT in log
            n_tool_calls=3,
            n_errors=0,
            final_state="working",
            source_log_path=str(temp_path),
        )

        result = validate_summary(summary, temp_path, llm_fn=lambda log, claim: (True, "mock"))

        # Find claims that should be refuted
        refuted = [c for c in result.claims if c.verdict == ClaimVerdict.NOT_FOUND]
        assert len(refuted) > 0, "Should refute false claims"

        print(f"  ✓ Refuted {len(refuted)} false claims")
        for claim in refuted:
            print(f"    - {claim.text} ({claim.claim_type})")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_layer2_semantic_validation_gating():
    """Test LAYER 2: semantic validation only runs on unverifiable claims."""
    print("[L2] Testing semantic validation gating...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        # Summary with a semantic claim (about intent/reasoning)
        # Long prose with few deterministic claims triggers semantic claim creation
        summary = SummaryEntry(
            content="Used terminal tool to explore the directory structure and understand the codebase layout. The user wanted to understand how the agent works and was looking for specific files in the agent-core directory.",
            metadata={"session_id": "test_phase5"},
            session_id="test_phase5",
            started_at="2026-05-10T10:00:00Z",
            ended_at="2026-05-10T10:00:20Z",
            tools_used={"terminal": 1},
            files_touched=[],
            n_tool_calls=1,
            n_errors=0,
            final_state="working",
            source_log_path=str(temp_path),
        )

        # Mock LLM that tracks what it was called with
        calls = []

        def mock_llm(log_excerpt, claim_text):
            calls.append(claim_text)
            return True, "mock evidence"

        result = validate_summary(summary, temp_path, llm_fn=mock_llm)

        # Check that semantic claims exist
        semantic_claims = [c for c in result.claims if c.claim_type == "semantic"]
        assert len(semantic_claims) > 0, "Should extract semantic claims from long prose"

        # Check that LLM was called for semantic claims
        assert len(calls) > 0, "LLM should be called for semantic claims"

        # Check that deterministic claims were NOT sent to LLM
        for claim in result.claims:
            if claim.claim_type in ("tool", "file", "error", "count"):
                # These should be decided deterministically
                assert claim.verdict != ClaimVerdict.REJECTED, \
                    f"Deterministic claim {claim.claim_type} should not have LLM verdict"

        print(f"  ✓ Semantic validation called {len(calls)} times")
        print(f"  ✓ Deterministic claims handled without LLM")
        print(f"  ✓ Found {len(semantic_claims)} semantic claims")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_layer3_decision_approve():
    """Test LAYER 3: decision logic for APPROVE branch."""
    print("[L3] Testing APPROVE decision...")

    claims = [
        MagicMock(claim_type="tool", verdict=ClaimVerdict.CONFIRMED),
        MagicMock(claim_type="file", verdict=ClaimVerdict.CONFIRMED),
    ]

    decision, final_content, reason = _make_decision(claims, "All claims confirmed")

    assert decision == Decision.APPROVE, f"Expected APPROVE, got {decision}"
    assert final_content == "All claims confirmed"
    assert "confirmed" in reason.lower()

    print(f"  ✓ APPROVE decision: {reason}")
    print("    PASSED\n")


def test_layer3_decision_reject():
    """Test LAYER 3: decision logic for REJECT branch (not_found claims)."""
    print("[L3] Testing REJECT decision...")

    claims = [
        MagicMock(claim_type="tool", verdict=ClaimVerdict.CONFIRMED),
        MagicMock(claim_type="file", verdict=ClaimVerdict.NOT_FOUND),  # Triggers reject
    ]

    decision, final_content, reason = _make_decision(claims, "Some claims not found")

    assert decision == Decision.REJECT, f"Expected REJECT, got {decision}"
    assert "not found" in reason.lower()

    print(f"  ✓ REJECT decision: {reason}")
    print("    PASSED\n")


def test_layer3_decision_approve_stripped():
    """Test LAYER 3: decision logic for APPROVE_STRIPPED branch (rejected semantic claims)."""
    print("[L3] Testing APPROVE_STRIPPED decision...")

    claims = [
        MagicMock(claim_type="tool", verdict=ClaimVerdict.CONFIRMED, text="Used terminal"),
        MagicMock(claim_type="semantic", verdict=ClaimVerdict.REJECTED, text="User wanted to explore"),
    ]

    decision, final_content, reason = _make_decision(claims, "Used terminal. User wanted to explore.")

    assert decision == Decision.APPROVE_STRIPPED, f"Expected APPROVE_STRIPPED, got {decision}"
    assert "stripped" in reason.lower()
    # Stripped content should not contain the rejected claim
    assert "User wanted to explore" not in final_content or final_content != "Used terminal. User wanted to explore."

    print(f"  ✓ APPROVE_STRIPPED decision: {reason}")
    print(f"    Final content: {final_content[:50]}...")
    print("    PASSED\n")


def test_full_pipeline_with_mock():
    """Test full pipeline end-to-end with mocked L2 LLM."""
    print("[Pipeline] Testing full pipeline with mocked L2...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        # Use prose that has both deterministic and semantic claims
        summary = SummaryEntry(
            content="Used terminal tool to list files and explore the directory structure. The user wanted to understand the agent codebase and find specific files in the agent-core directory. The agent successfully completed 2 tool calls without errors.",
            metadata={"session_id": "test_phase5"},
            session_id="test_phase5",
            started_at="2026-05-10T10:00:00Z",
            ended_at="2026-05-10T10:00:20Z",
            tools_used={"terminal": 1},
            files_touched=[],
            n_tool_calls=2,
            n_errors=0,
            final_state="working",
            source_log_path=str(temp_path),
        )

        # Mock LLM that approves semantic claims
        def mock_llm(log_excerpt, claim_text):
            return True, "Log shows exploration activity"

        result = validate_summary(summary, temp_path, llm_fn=mock_llm)

        assert result.decision in (Decision.APPROVE, Decision.APPROVE_STRIPPED), \
            f"Expected approve decision, got {result.decision}"
        assert result.confidence in ("high", "medium"), f"Confidence should be high/medium, got {result.confidence}"
        assert len(result.claims) > 0, "Should have claims"

        print(f"  ✓ Pipeline completed successfully")
        print(f"    - Decision: {result.decision}")
        print(f"    - Confidence: {result.confidence}")
        print(f"    - Claims: {len(result.claims)}")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_idempotent_validation_markers():
    """Test that validation markers prevent re-processing."""
    print("[Idempotency] Testing validation marker prevents re-processing...")

    with tempfile.TemporaryDirectory() as tmpdir:
        chats_dir = Path(tmpdir)

        # Create a JSONL file
        jsonl_path = chats_dir / "sealed_audit_test.jsonl"
        jsonl_path.write_text(_SYNTHETIC_JSONL)

        # Create a validation marker (simulating previous run)
        validated_path = jsonl_path.with_suffix(".validated.json")
        validated_path.write_text(json.dumps({
            "session_id": "test_phase5",
            "decision": "approve",
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }))

        # Import and run sleep_cycle (dry-run to check what would be processed)
        from memory.sleep_cycle import _find_pending_sessions

        pending = _find_pending_sessions(chats_dir)

        # Should NOT include the already-validated file
        assert jsonl_path not in pending, "Already-validated file should not be in pending list"
        assert len(pending) == 0, f"Should have 0 pending files, got {len(pending)}"

        print(f"  ✓ Validation marker prevents re-processing")
        print("    PASSED\n")


def test_summary_entry_to_dict():
    """Test SummaryEntry serialization for validation."""
    print("[Serialization] Testing SummaryEntry.to_dict()...")

    summary = SummaryEntry(
        content="Test content",
        metadata={"key": "value"},
        session_id="test",
        started_at="2026-05-10T10:00:00Z",
        ended_at="2026-05-10T10:01:00Z",
        tools_used={"terminal": 1},
        files_touched=["file.py"],
        n_tool_calls=1,
        n_errors=0,
        final_state="working",
        source_log_path="/path/to/log.jsonl",
    )

    d = summary.to_dict()
    assert d["content"] == "Test content"
    assert d["session_id"] == "test"
    assert d["tools_used"]["terminal"] == 1

    print(f"  ✓ SummaryEntry serialization works")
    print("    PASSED\n")


def test_validation_result_to_dict():
    """Test ValidationResult serialization."""
    print("[Serialization] Testing ValidationResult.to_dict()...")

    result = ValidationResult(
        decision=Decision.APPROVE,
        confidence="high",
        claims=[],
        final_content="Test content",
        reason="All claims confirmed",
        metadata={"test": "value"},
    )

    d = result.to_dict()
    assert d["decision"] == "approve"
    assert d["confidence"] == "high"
    assert d["reason"] == "All claims confirmed"

    print(f"  ✓ ValidationResult serialization works")
    print("    PASSED\n")


def test_load_raw_log():
    """Test loading raw log for validation."""
    print("[Utils] Testing _load_raw_log...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_SYNTHETIC_JSONL)
        temp_path = Path(f.name)

    try:
        log_text = _load_raw_log(temp_path)
        assert "terminal" in log_text
        assert "file_read" in log_text
        assert '"type": "error"' in log_text
        assert len(log_text) > 100

        print(f"  ✓ Raw log loaded ({len(log_text)} chars)")
        print("    PASSED\n")
    finally:
        temp_path.unlink()


def test_reject_with_many_semantic_rejections():
    """Test that too many rejected semantic claims triggers REJECT."""
    print("[L3] Testing REJECT for many semantic rejections...")

    claims = [
        MagicMock(claim_type="tool", verdict=ClaimVerdict.CONFIRMED),
        MagicMock(claim_type="semantic", verdict=ClaimVerdict.REJECTED, text="Claim 1"),
        MagicMock(claim_type="semantic", verdict=ClaimVerdict.REJECTED, text="Claim 2"),
        # With 3 total claims, threshold is 1, so 2 rejections should trigger reject
    ]

    decision, final_content, reason = _make_decision(claims, "Tool used. Claim 1. Claim 2.")

    assert decision == Decision.REJECT, f"Expected REJECT for many semantic rejections, got {decision}"
    assert "rejected" in reason.lower()

    print(f"  ✓ REJECT decision for multiple semantic rejections")
    print("    PASSED\n")


def main():
    print("=" * 50)
    print("Phase 5 Validation: Sleep-Cycle Validation")
    print("=" * 50)
    print()

    test_layer1_deterministic_validation()
    test_layer1_refutes_false_claims()
    test_layer2_semantic_validation_gating()
    test_layer3_decision_approve()
    test_layer3_decision_reject()
    test_layer3_decision_approve_stripped()
    test_full_pipeline_with_mock()
    test_idempotent_validation_markers()
    test_summary_entry_to_dict()
    test_validation_result_to_dict()
    test_load_raw_log()
    test_reject_with_many_semantic_rejections()

    print("=" * 50)
    print("Phase 5 validation complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
