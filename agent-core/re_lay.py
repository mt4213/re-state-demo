"""re_lay — LLM request router for re_cur engine."""

import json
import logging
import os
import urllib.request
import urllib.error
import copy

logger = logging.getLogger("re_lay")

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080")
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))
DEFAULT_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

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
                "required": ["thought", "command"]
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
                "required": ["thought", "path"]
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
                "required": ["thought", "path", "content"]
            }
        }
    }
]


def send_stream(messages, on_chunk, base_url=None, max_tokens=None, timeout=None, tools=TOOLS):
    """Send messages to llama.cpp with streaming and return the parsed response dict."""
    base_url = base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)
    max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
    timeout = timeout or int(os.getenv("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    model = os.getenv("LLM_MODEL", "local")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Build messages without assistant prefill to avoid "Assistant response prefill 
    # is incompatible with enable_thinking" error with Qwen3 thinking mode.
    clean_messages = []
    for msg in copy.deepcopy(messages):
        role = msg.get("role", "")
        if role == "system":
            # Keep system messages as-is, but only if they have content
            if msg.get("content", "").strip():
                clean_messages.append({"role": "system", "content": msg.get("content")})
        elif role == "tool":
            # Tool results are essential - include them
            clean_msg = {"role": "tool", "tool_call_id": msg.get("tool_call_id", ""), "content": msg.get("content", "")}
            clean_messages.append(clean_msg)
        elif role == "user":
            # User messages are important
            clean_msg = {"role": "user", "content": msg.get("content", "")}
            clean_messages.append(clean_msg)
        elif role in ("assistant", "self", "entity"):
            # Only include assistant messages if they have content or tool_calls.
            # Empty assistant messages with no content and no tool_calls cause
            # "Assistant response prefill is incompatible with enable_thinking" errors.
            tc = msg.get("tool_calls")
            content = msg.get("content")
            if tc or (content and content.strip()):
                assistant_msg = {"role": role}
                if tc:
                    assistant_msg["tool_calls"] = tc
                if content and content.strip():
                    assistant_msg["content"] = content
                clean_messages.append(assistant_msg)
            # else: skip this empty assistant message

    # Remove empty system messages
    clean_messages = [
        m for m in clean_messages
        if not (m.get("role") == "system" and not (m.get("content") or "").strip())
    ]
    
    # Ensure we have at least one message with content (required by API)
    if not clean_messages:
        # Fall back: keep first message that has actual content or tool_calls
        for msg in copy.deepcopy(messages):
            role = msg.get("role", "")
            if role in ("system", "user", "assistant", "self", "entity"):
                content = msg.get("content", "")
                tc = msg.get("tool_calls")
                if (content and content.strip()) or tc:
                    clean_messages.append(msg)
                    break

    payload = {
        "model": model,
        "messages": clean_messages,
        "max_tokens": max_tokens,
        "temperature": 1.05,
        "stream": True,
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
            accumulated_content = ""
            accumulated_reasoning = ""
            tool_calls_acc = {}
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data_str = line[len("data: "):]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0]["delta"]
                        
                        if "content" in delta and delta["content"]:
                            accumulated_content += delta["content"]
                        
                        if "reasoning_content" in delta and delta["reasoning_content"]:
                            accumulated_reasoning += delta["reasoning_content"]
                        
                        if "tool_calls" in delta:
                            for tc_delta in delta["tool_calls"]:
                                idx = tc_delta["index"]
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                if "id" in tc_delta:
                                    tool_calls_acc[idx]["id"] = tc_delta["id"]
                                if "type" in tc_delta:
                                    tool_calls_acc[idx]["type"] = tc_delta["type"]
                                if "function" in tc_delta:
                                    fn = tc_delta["function"]
                                    if "name" in fn:
                                        tool_calls_acc[idx]["function"]["name"] += fn["name"]
                                    if "arguments" in fn:
                                        tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]
                        
                        on_chunk(accumulated_content, list(tool_calls_acc.values()), accumulated_reasoning)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass

            final_tool_calls = list(tool_calls_acc.values())
            return {
                "content": accumulated_content or None,
                "tool_calls": final_tool_calls if final_tool_calls else None,
                "reasoning": accumulated_reasoning or None,
                "error": None
            }
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

    # Build messages without assistant prefill to avoid "Assistant response prefill 
    # is incompatible with enable_thinking" error with Qwen3 thinking mode.
    clean_messages = []
    for msg in copy.deepcopy(messages):
        role = msg.get("role", "")
        if role == "system":
            # Keep system messages as-is, but only if they have content
            if msg.get("content", "").strip():
                clean_messages.append({"role": "system", "content": msg.get("content")})
        elif role == "tool":
            # Tool results are essential - include them
            clean_msg = {"role": "tool", "tool_call_id": msg.get("tool_call_id", ""), "content": msg.get("content", "")}
            clean_messages.append(clean_msg)
        elif role == "user":
            # User messages are important
            clean_msg = {"role": "user", "content": msg.get("content", "")}
            clean_messages.append(clean_msg)
        elif role in ("assistant", "self", "entity"):
            # Only include assistant messages if they have content or tool_calls.
            # Empty assistant messages with no content and no tool_calls cause
            # "Assistant response prefill is incompatible with enable_thinking" errors.
            tc = msg.get("tool_calls")
            content = msg.get("content")
            if tc or (content and content.strip()):
                assistant_msg = {"role": role}
                if tc:
                    assistant_msg["tool_calls"] = tc
                if content and content.strip():
                    assistant_msg["content"] = content
                clean_messages.append(assistant_msg)
            # else: skip this empty assistant message

    # Remove empty system messages
    clean_messages = [
        m for m in clean_messages
        if not (m.get("role") == "system" and not (m.get("content") or "").strip())
    ]
    
    # Ensure we have at least one message with content (required by API)
    if not clean_messages:
        # Fall back: keep first message that has actual content or tool_calls
        for msg in copy.deepcopy(messages):
            role = msg.get("role", "")
            if role in ("system", "user", "assistant", "self", "entity"):
                content = msg.get("content", "")
                tc = msg.get("tool_calls")
                if (content and content.strip()) or tc:
                    clean_messages.append(msg)
                    break

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
