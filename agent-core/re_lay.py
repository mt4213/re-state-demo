"""re_lay — LLM request router for re_cur engine."""

import json
import logging
import os
import urllib.request
import urllib.error
import copy

logger = logging.getLogger("re_lay")

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_MAX_TOKENS = 512
DEFAULT_TIMEOUT = 120

# Tool definitions for the LLM (OpenAI function-calling format)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a shell command. Returns stdout and stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Brief reason for this action (under 20 words)."
                    },
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Brief reason for this action (under 20 words)."
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file to read."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file. Creates or overwrites.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Brief reason for this action (under 20 words)."
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write."
                    }
                },
                "required": ["path", "content"]
            }
        }
    }
]


def send(messages, base_url=None, max_tokens=None, timeout=None, tools=TOOLS):
    """Send messages to llama.cpp and return the parsed response dict.
    
    Returns dict with keys:
      - "content": str or None (text response)
      - "tool_calls": list of tool call dicts, or None
      - "error": str if request failed
    """
    base_url = base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)
    max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
    timeout = timeout or int(os.getenv("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    model = os.getenv("LLM_MODEL", "local")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Strip _thought annotations before sending to LLM
    clean_messages = copy.deepcopy(messages)
    for msg in clean_messages:
        for tc in msg.get("tool_calls") or []:
            tc.pop("_thought", None)

    # Gemini (and some other providers) reject requests where `contents` is empty.
    # The system role maps to systemInstruction, not contents — so a system-only
    # message list leaves contents empty. Fix: drop empty system messages and
    # ensure at least one user message exists in the send-copy only.
    clean_messages = [
        m for m in clean_messages
        if not (m.get("role") == "system" and not (m.get("content") or "").strip())
    ]

    payload = {
        "model": model,
        "messages": clean_messages,
        "max_tokens": max_tokens,
        "temperature": 1.05,
    }
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode("utf-8")
    
    api_key = os.getenv("LLM_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.lower() != "dummy":
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.error("LLM HTTP %s: %s", e.code, error_body)
        return {"content": None, "tool_calls": None, "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        logger.error("LLM request failed: %s", e)
        return {"content": None, "tool_calls": None, "error": str(e)}

    # Parse response
    try:
        choice = data["choices"][0]
        msg = choice["message"]
        return {
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls"),
            "error": None,
        }
    except (KeyError, IndexError) as e:
        logger.error("Unexpected LLM response structure: %s", e)
        return {"content": None, "tool_calls": None, "error": f"Bad response: {e}"}
