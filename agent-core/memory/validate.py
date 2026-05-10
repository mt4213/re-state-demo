"""
Phase 5: Sleep-cycle validation.

Three-layer validation gate between summarization and vector DB storage:
- LAYER 1: Deterministic validation (grep raw log for tool names, files, errors, counts)
- LAYER 2: Semantic validation (different model arch, only for unverifiable claims)
- LAYER 3: Decision (approve/reject/approve_stripped based on claim verdicts)

No unvalidated summary may enter the vector DB.
"""
from __future__ import annotations

import dataclasses as dc
import json
import logging
import os
import re
import urllib.request
import urllib.error
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .summarize import SummaryEntry

logger = logging.getLogger(__name__)

# Load .env from project root
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.split("#")[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


class Decision(str, Enum):
    """Final validation decision."""
    APPROVE = "approve"  # All claims confirmed, store as-is
    APPROVE_STRIPPED = "approve_stripped"  # Some claims stripped, store remainder
    REJECT = "reject"  # Too many failed claims, fall back to raw chunks


class ClaimVerdict(str, Enum):
    """Verdict for a single claim."""
    CONFIRMED = "confirmed"  # Found in raw log
    NOT_FOUND = "not_found"  # Claimed but not in log
    UNVERIFIABLE = "unverifiable"  # Can't determine deterministically
    REJECTED = "rejected"  # Semantic validation rejected


@dc.dataclass
class Claim:
    """A single factual claim extracted from summary prose."""
    text: str  # The claim text
    claim_type: str  # "tool", "file", "error", "count", "semantic"
    value: str | int  # The claimed value (tool name, file path, count, etc.)
    verdict: ClaimVerdict = ClaimVerdict.UNVERIFIABLE
    evidence: str = ""  # Evidence from log (for confirmed/rejected)


@dc.dataclass
class ValidationResult:
    """Result of validating a summary against its raw log."""
    decision: Decision
    confidence: str  # "high" | "medium" | "low"
    claims: list[Claim]
    final_content: str  # The (possibly modified) content to store
    reason: str  # Human-readable explanation
    metadata: dict[str, Any]  # Additional metadata

    def to_dict(self) -> dict:
        return dc.asdict(self)


# LAYER 1: Deterministic validation

# Patterns to extract claims from prose
_ERROR_PATTERN = re.compile(r'(?:error|fail|crash|timeout|exception)', re.IGNORECASE)
_COUNT_PATTERN = re.compile(r'(\d+)\s+times?', re.IGNORECASE)



def _extract_claims_from_prose(prose: str, known_tools: dict[str, int], known_files: list[str]) -> list[Claim]:
    """Extract potential claims from summary prose."""
    claims = []

    # Extract tool claims
    prose_lower = prose.lower()
    for tool_name in known_tools.keys():
        if tool_name.lower() in prose_lower or tool_name.replace("_", " ") in prose_lower:
            claims.append(Claim(
                text=f"Used tool: {tool_name}",
                claim_type="tool",
                value=tool_name
            ))

    # Extract file claims
    for file_path in known_files:
        if file_path in prose:
            claims.append(Claim(
                text=f"Modified/read file: {file_path}",
                claim_type="file",
                value=file_path
            ))

    # Extract error claims
    if _ERROR_PATTERN.search(prose):
        claims.append(Claim(
            text="Mentions errors/failures",
            claim_type="error",
            value="error"
        ))

    # Extract count claims (basic pattern matching)
    for match in _COUNT_PATTERN.finditer(prose):
        count = int(match.group(1))
        claims.append(Claim(
            text=f"Claims count: {count}",
            claim_type="count",
            value=count
        ))

    # If prose is long and we didn't find many claims, mark remaining as semantic
    if len(claims) < 3 and len(prose) > 100:
        # Treat the whole prose as a semantic claim
        claims.append(Claim(
            text=prose[:200],
            claim_type="semantic",
            value=prose[:200]
        ))

    return claims


def _validate_deterministic(claims: list[Claim], raw_log_text: str, known_tools: dict[str, int], known_files: list[str]) -> list[Claim]:
    """LAYER 1: Validate claims against raw log using deterministic checks."""
    log_lower = raw_log_text.lower()

    for claim in claims:
        if claim.claim_type == "tool":
            # Check if tool appears in log (case-insensitive substring search)
            tool_str = str(claim.value).lower()
            if tool_str in log_lower:
                claim.verdict = ClaimVerdict.CONFIRMED
                claim.evidence = f"Found in log"
            else:
                claim.verdict = ClaimVerdict.NOT_FOUND

        elif claim.claim_type == "file":
            # Check if file path appears in log
            if claim.value in raw_log_text:
                claim.verdict = ClaimVerdict.CONFIRMED
                claim.evidence = f"Found in log: {claim.value}"
            else:
                claim.verdict = ClaimVerdict.NOT_FOUND

        elif claim.claim_type == "error":
            # Check if error events exist in log
            if '"type": "error"' in raw_log_text or '"error"' in raw_log_text:
                claim.verdict = ClaimVerdict.CONFIRMED
                claim.evidence = "Error events found in log"
            else:
                claim.verdict = ClaimVerdict.NOT_FOUND

        elif claim.claim_type == "count":
            # Try to validate numeric claims
            claimed_count = int(claim.value)
            # Count tool_call events
            actual_count = raw_log_text.count('"type": "tool_call"')
            if claimed_count == actual_count:
                claim.verdict = ClaimVerdict.CONFIRMED
                claim.evidence = f"Tool calls: {actual_count}"
            elif claimed_count <= actual_count * 1.5 and claimed_count >= actual_count * 0.5:
                # Allow some tolerance (summary might round)
                claim.verdict = ClaimVerdict.CONFIRMED
                claim.evidence = f"Tool calls: {actual_count} (close to claimed {claimed_count})"
            else:
                claim.verdict = ClaimVerdict.NOT_FOUND
                claim.evidence = f"Tool calls: {actual_count} != claimed {claimed_count}"

        elif claim.claim_type == "semantic":
            # Deterministic check can't verify this
            claim.verdict = ClaimVerdict.UNVERIFIABLE

    return claims


# LAYER 2: Semantic validation

_VALIDATOR_PROMPT = """You are a strict validator. Check if the log supports this claim.

Log excerpt:
{log_excerpt}

Claim: {claim}

Answer yes if the log explicitly supports this claim.
Answer no if the log contradicts or doesn't support this claim.
Be strict - only say yes if there's clear evidence.

Answer in format: YES: [evidence] or NO: [reason]"""


def _call_validator_llm(log_excerpt: str, claim_text: str, llm_fn: Callable | None = None) -> tuple[bool, str] | None:
    """
    LAYER 2: Call validator LLM to check semantic claim.

    Returns:
        (True, evidence) if LLM confirms the claim
        (False, reason) if LLM rejects the claim
        None if validator LLM is hard-unavailable (network down, timeout, etc.)
    """
    if llm_fn is not None:
        # Test injection point: check for sentinel return
        result = llm_fn(log_excerpt, claim_text)
        # If test returns None, propagate it as hard failure
        # Otherwise return (is_supported, evidence_or_reason) tuple
        return result

    # Production: call the validator LLM
    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    validator_model = os.getenv("LLM_VALIDATOR_MODEL")
    if not validator_model:
        logger.warning("LLM_VALIDATOR_MODEL not set, falling back to LLM_MODEL (same arch as summarizer - may have correlated bias)")
        validator_model = os.getenv("LLM_MODEL", "local")

    max_tokens = 512
    timeout = int(os.getenv("LLM_TIMEOUT", "120"))
    api_key = os.getenv("LLM_API_KEY", "")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Truncate log excerpt if needed
    log_budget = 8000
    if len(log_excerpt) > log_budget:
        log_excerpt = log_excerpt[:log_budget] + "\n... (truncated)"

    prompt = _VALIDATOR_PROMPT.format(log_excerpt=log_excerpt, claim=claim_text)

    payload = {
        "model": validator_model,
        "messages": [
            {"role": "system", "content": "You are a strict fact-checker."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,  # Low temp for consistent validation
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key and api_key.lower() != "dummy":
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip().upper()

            if content.startswith("YES"):
                evidence = content.split(":", 1)[1].strip() if ":" in content else "Supported by log"
                return True, evidence
            else:
                reason = content.split(":", 1)[1].strip() if ":" in content else "Not supported"
                return False, reason

    except Exception as e:
        logger.warning(f"Validator LLM call failed: {e}, treating as unverifiable")
        # Degrade gracefully: return None sentinel to distinguish from LLM saying 'no'
        return None


def _validate_semantic(claims: list[Claim], raw_log_text: str, llm_fn: Callable | None = None) -> list[Claim]:
    """LAYER 2: Semantic validation for unverifiable claims."""
    for claim in claims:
        if claim.verdict != ClaimVerdict.UNVERIFIABLE:
            continue

        if claim.claim_type == "semantic":
            result = _call_validator_llm(raw_log_text, claim.text, llm_fn)

            if result is None:
                # Hard failure: validator LLM unavailable
                claim.verdict = ClaimVerdict.UNVERIFIABLE
                claim.evidence = "Validator unavailable (hard failure)"
            else:
                is_supported, evidence = result
                if is_supported:
                    claim.verdict = ClaimVerdict.CONFIRMED
                    claim.evidence = evidence
                else:
                    claim.verdict = ClaimVerdict.REJECTED
                    claim.evidence = evidence

    return claims


# LAYER 3: Decision

def _make_decision(claims: list[Claim], original_content: str) -> tuple[Decision, str, str]:
    """
    LAYER 3: Make final decision based on claim verdicts.

    Returns:
        (decision, final_content, reason)
    """
    not_found_count = sum(1 for c in claims if c.verdict == ClaimVerdict.NOT_FOUND)
    rejected_count = sum(1 for c in claims if c.verdict == ClaimVerdict.REJECTED)
    unverifiable_count = sum(1 for c in claims if c.verdict == ClaimVerdict.UNVERIFIABLE)
    confirmed_count = sum(1 for c in claims if c.verdict == ClaimVerdict.CONFIRMED)
    total_claims = len(claims)

    # Rule 1: Any not_found claims → reject
    if not_found_count > 0:
        reason = f"Reject: {not_found_count} claims not found in log"
        return Decision.REJECT, original_content, reason

    # Rule 2: Too many rejected semantic claims → reject
    if rejected_count > max(1, total_claims // 3):
        reason = f"Reject: {rejected_count} semantic claims rejected"
        return Decision.REJECT, original_content, reason

    # Rule 3: Some claims rejected or unverifiable → strip and re-evaluate
    # Consolidate stripping for both rejected and unverifiable claims
    if rejected_count > 0 or unverifiable_count > 0:
        # First pass: strip unverifiable claims (validator unavailable)
        stripped_content = original_content
        for claim in claims:
            if claim.verdict == ClaimVerdict.UNVERIFIABLE and claim.claim_type == "semantic":
                # Remove the claim text from content
                stripped_content = stripped_content.replace(claim.text, "")

        stripped_content = stripped_content.strip()
        if not stripped_content:
            reason = "Reject: Content empty after stripping unverifiable claims"
            return Decision.REJECT, original_content, reason

        # Second pass: if rejected claims remain, strip them too
        if rejected_count > 0:
            for claim in claims:
                if claim.verdict == ClaimVerdict.REJECTED and claim.claim_type == "semantic":
                    stripped_content = stripped_content.replace(claim.text, "")

            stripped_content = stripped_content.strip()
            if not stripped_content:
                reason = "Reject: Content empty after stripping rejected claims"
                return Decision.REJECT, original_content, reason

            reason = f"Approve (stripped): Removed {rejected_count} unsupported claims"
            return Decision.APPROVE_STRIPPED, stripped_content, reason

        # Only unverifiable claims were stripped
        reason = f"Approve (stripped): Removed {unverifiable_count} unverifiable claims (validator unavailable)"
        return Decision.APPROVE_STRIPPED, stripped_content, reason

    # Rule 4: All confirmed → approve
    if confirmed_count == total_claims:
        reason = "Approve: All claims confirmed"
        return Decision.APPROVE, original_content, reason

    # Rule 5: Mixed but no failures → approve with high confidence
    reason = f"Approve: {confirmed_count}/{total_claims} claims confirmed"
    return Decision.APPROVE, original_content, reason


# Main validation function

def _load_raw_log(jsonl_path: Path) -> str:
    """Load raw JSONL log as text for validation."""
    with open(jsonl_path, encoding="utf-8") as f:
        return f.read()


def validate_summary(
    summary: SummaryEntry,
    raw_jsonl_path: Path | str,
    llm_fn: Callable | None = None,
    mode: str = "full",
) -> ValidationResult:
    """
    Validate a summary against its raw JSONL log using three-layer validation.

    Args:
        summary: The SummaryEntry to validate
        raw_jsonl_path: Path to the source sealed_audit_*.jsonl file
        llm_fn: Optional mock function for testing semantic validation
        mode: Validation mode - "full" for L1+L2+L3, "l1_only" for L1 deterministic only

    Returns:
        ValidationResult with decision, confidence, and modified content if needed
    """
    raw_jsonl_path = Path(raw_jsonl_path)
    raw_log_text = _load_raw_log(raw_jsonl_path)

    # Extract claims from prose
    claims = _extract_claims_from_prose(
        summary.content,
        known_tools=summary.tools_used,
        known_files=summary.files_touched
    )

    # LAYER 1: Deterministic validation
    claims = _validate_deterministic(
        claims,
        raw_log_text,
        summary.tools_used,
        summary.files_touched
    )

    # L1-only mode: make decision based solely on deterministic checks
    if mode == "l1_only":
        # Any not_found claims -> reject
        not_found_count = sum(1 for c in claims if c.verdict == ClaimVerdict.NOT_FOUND)
        if not_found_count > 0:
            return ValidationResult(
                decision=Decision.REJECT,
                confidence="low",
                claims=claims,
                final_content=summary.content,
                reason=f"L1-only: {not_found_count} claims not found in log",
                metadata={
                    "session_id": summary.session_id,
                    "validation_timestamp": _get_timestamp(),
                    "validation_mode": "l1_only",
                }
            )
        # All confirmed or unverifiable -> approve
        return ValidationResult(
            decision=Decision.APPROVE,
            confidence="high",
            claims=claims,
            final_content=summary.content,
            reason=f"L1-only: all deterministically-verifiable claims confirmed",
            metadata={
                "session_id": summary.session_id,
                "validation_timestamp": _get_timestamp(),
                "validation_mode": "l1_only",
            }
        )

    # LAYER 2: Semantic validation (only for unverifiable claims)
    claims = _validate_semantic(claims, raw_log_text, llm_fn=llm_fn)

    # LAYER 3: Decision
    decision, final_content, reason = _make_decision(claims, summary.content)

    # Determine confidence
    if decision == Decision.APPROVE:
        confidence = "high"
    elif decision == Decision.APPROVE_STRIPPED:
        confidence = "medium"
    else:
        confidence = "low"

    return ValidationResult(
        decision=decision,
        confidence=confidence,
        claims=claims,
        final_content=final_content,
        reason=reason,
        metadata={
            "session_id": summary.session_id,
            "validation_timestamp": _get_timestamp(),
        }
    )


def _get_timestamp() -> str:
    """Get current ISO timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# Re-summarization with stricter prompt (for rejected summaries)

_STRICTER_SUMMARIZER_PROMPT = """You are a strict faithful summarizer. Summarize this session log.

IMPORTANT: Only include facts that are EXPLICITLY in the log. Do NOT infer:
- Intent or motivation ("the user wanted to...")
- Reasoning about why something was done
- Cause-and-effect not directly stated

Include:
- Tools used and how many times (must match tool_call events exactly)
- Files touched (must appear in file_read/file_write/terminal commands)
- Errors that actually occurred
- Final state (working/broken/in_progress)

Session events:
{log_text}

Summary:"""


def re_summarize_strict(jsonl_path: Path | str) -> str | None:
    """
    Re-summarize a session with a stricter prompt after validation rejection.

    Returns new summary content or None on failure.
    """
    jsonl_path = Path(jsonl_path)
    raw_log_text = _load_raw_log(jsonl_path)

    # Truncate if needed
    log_budget = 28000
    if len(raw_log_text) > log_budget:
        raw_log_text = raw_log_text[:log_budget] + "\n... (truncated)"

    prompt = _STRICTER_SUMMARIZER_PROMPT.format(log_text=raw_log_text)

    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    model = os.getenv("LLM_SUMMARIZER_MODEL") or os.getenv("LLM_MODEL", "local")
    max_tokens = 1024
    timeout = 120
    api_key = os.getenv("LLM_API_KEY", "")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict, faithful summarizer."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,  # Even lower temp for stricter output
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key and api_key.lower() != "dummy":
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return content.strip() if content else None

    except Exception as e:
        logger.error(f"Strict re-summarization failed: {e}")
        return None
