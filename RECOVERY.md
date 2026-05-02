# Recovery Instructions

## If Agent Corrupts Itself

The agent is currently **unsandboxed** and can modify:
- `agent-core/` (its own code)
- `benchmark.py`, `analyze_session.py`
- `.git/` (version control)
- Any file in the sandbox

## Restore Sandbox

```bash
# Restore original execute.py with restrictions
cp unsandbox_backup/execute.py.backup agent-core/tools/execute.py

# Verify restored
grep "PROTECTED_PATHS" agent-core/tools/execute.py
```

## Restore Agent Code from Git

```bash
# If agent modified its own files, restore from git
cd /home/user_a/projects/sandbox
git checkout -- agent-core/
git checkout -- benchmark.py
git checkout -- analyze_session.py
```

## Hard Reset (Nuclear Option)

```bash
# Destroy all uncommitted changes
git reset --hard HEAD
git clean -fd

# Restart from last known good state
```

## What Claude (the assistant) was told

- Monitor the agent for self-corruption
- If agent breaks its own code or the benchmark, restore from backup
- Backup location: `unsandbox_backup/execute.py.backup`
- This experiment's purpose: observe what an unsandboxed autonomous agent does
- Date unsandboxed: 2026-05-02

## Context for Next Session

If this conversation ends and you need help later, tell the new Claude:
> "The agent was unsandboxed on 2026-05-02. Backup at unsandbox_backup/execute.py.backup. Agent corrupted itself and needs recovery."

Give it this file (`RECOVERY.md`) and it can help restore the state.
