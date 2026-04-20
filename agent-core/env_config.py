"""Shared environment configuration — loads .env before any module-level os.getenv() calls."""

import os

_loaded = False

def load_env():
    """Load .env into os.environ without overriding existing vars.
    
    Looks for .env at project root (parent of agent-core/).
    Call this at the very start of any module that reads env vars at module level.
    """
    global _loaded
    if _loaded:
        return  # Already loaded by another module
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    env_path = os.path.join(project_root, ".env")
    
    if not os.path.exists(env_path):
        # Try current working directory as fallback
        env_path = os.path.join(os.getcwd(), ".env")
    
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                # Strip inline comments (e.g. "# comment" after value)
                value = value.split("#")[0].strip()
                os.environ.setdefault(key.strip(), value)
    
    _loaded = True

# Load env vars immediately when this module is imported
load_env()