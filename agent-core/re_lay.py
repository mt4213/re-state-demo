"""
re_lay — Robust LLM request router for re_cur engine. 
Fixes context-stripping issues while maintaining compatibility with Qwen/Thinking models,
and ensures strict API adherence for tool calling.
"""

import env_config  # noqa: F401 - ensures .env is loaded before module-level os.getenv() calls
import json
import logging
import os
import urllib.request
import urllib.error
import copy

logger = logging.getLogger("re_lay")

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080")
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
DEFAULT_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
DEFAULT_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))

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
                    "thought": {"type": "string", "description": "Brief reason for this action."},
                    "command": {"type": "string", "description": "The bash command to execute."}
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
                    "thought": {"type": "string", "description": "Brief reason for this action."},
                    "path": {"type": "string", "description": "Absolute path to the file to read."}
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
                    "thought": {"type": "string", "description": "Brief reason for this action."},
                    "path": {"type": "string", "description": "Absolute path to the file."},
                    "content": {"type": "string", "description": "The content to write."}
                },
                "required": ["thought", "path", "content"]
            }
        }
    }
]

def _prepare_messages(messages):
    """
    Normalizes message history. Reconstructs assistant messages with embedded 
    thoughts to preserve context without triggering prefill errors.
    Ensures strict API compatibility for tool-calling formats.
    """
    clean_messages = []

    for msg in copy.deepcopy(messages):
        role = msg.get("role", "")
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning")
        tool_calls = msg.get("tool_calls")

        if role == "system":
            if content.strip():
                clean_messages.append({"role": "system", "content": content})
        
        elif role == "user":
            clean_messages.append({"role": "user", "content": content})
            
        elif role == "tool":
            clean_messages.append({
                "role": "tool", 
                "tool_call_id": msg.get("tool_call_id", ""), 
                "content": content
            })
            
        elif role in ("assistant", "self", "entity"):
            new_msg = {"role": "assistant"}
            
            # Wrap previous reasoning in tags so the model sees it as past context
            if reasoning:
                content = f"<thought>\n{reasoning}\n</thought>\n{content}"
            
            # OpenAI/vLLM strictness: Provide an empty content string if there are tool_calls
            if content.strip():
                new_msg["content"] = content.strip()
            elif tool_calls:
                new_msg["content"] = "" 
            
            if tool_calls:
                new_msg["tool_calls"] = tool_calls
            
            # Ensure message isn't empty (API requirement)
            if "content" in new_msg or "tool_calls" in new_msg:
                clean_messages.append(new_msg)

    # Fallback: Ensure at least one 'user' message exists to satisfy strict Jinja templates
    if not any(msg.get("role") == "user" for msg in clean_messages):
        clean_messages.append({"role": "user", "content": "Continue."})
        
    return clean_messages

def send_stream(messages, on_chunk, base_url=None, max_tokens=None, timeout=None, tools=TOOLS):
    """
    Send messages to LLM with streaming and full context preservation.
    """
    base_url = base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)
    max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
    timeout = timeout or int(os.getenv("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    model = os.getenv("LLM_MODEL", "local")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    clean_messages = _prepare_messages(messages)

    payload = {
        "model": model,
        "messages": clean_messages,
        "max_tokens": max_tokens,
        "temperature": float(os.getenv("LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE))),
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode("utf-8")
    api_key = os.getenv("LLM_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.lower() != "dummy":
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            accumulated_content = ""
            accumulated_reasoning = ""
            tool_calls_acc = {}
            
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line or line.startswith(":"): continue
                if line.startswith("data: "):
                    data_str = line[len("data: "):]
                    if data_str == "[DONE]": break
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
                                
                                if "id" in tc_delta: tool_calls_acc[idx]["id"] = tc_delta["id"]
                                if "type" in tc_delta: tool_calls_acc[idx]["type"] = tc_delta["type"]
                                
                                if "function" in tc_delta:
                                    fn = tc_delta["function"]
                                    if "name" in fn: tool_calls_acc[idx]["function"]["name"] += fn["name"]
                                    if "arguments" in fn: tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]
                        
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
        logger.error("Streaming request failed: %s", e)
        return {"content": None, "tool_calls": None, "error": str(e)}

def send(messages, base_url=None, max_tokens=None, timeout=None, tools=TOOLS):
    """
    Non-streaming version of the request router.
    """
    base_url = base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)
    max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
    timeout = timeout or int(os.getenv("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    model = os.getenv("LLM_MODEL", "local")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    clean_messages = _prepare_messages(messages)

    payload = {
        "model": model,
        "messages": clean_messages,
        "max_tokens": max_tokens,
        "temperature": float(os.getenv("LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE))),
    }
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode("utf-8")
    api_key = os.getenv("LLM_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.lower() != "dummy":
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            msg = choice["message"]
            return {
                "content": msg.get("content"),
                "tool_calls": msg.get("tool_calls"),
                "reasoning": msg.get("reasoning_content"), 
                "error": None,
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
        logger.error("Request failed: %s", e)
        return {"content": None, "tool_calls": None, "error": str(e)}