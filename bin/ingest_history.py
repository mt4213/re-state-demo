#!/usr/bin/env python3
"""
CLI shim: adds agent-core/ to sys.path and runs memory.ingest.main().
Usage: python3 bin/ingest_history.py
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_AGENT_CORE = os.path.join(_REPO_ROOT, "..", "agent-core")
sys.path.insert(0, os.path.normpath(_AGENT_CORE))

from memory.ingest import main  # noqa: E402

if __name__ == "__main__":
    main()
