"""re_cur — Core ContReAct loop for autonomous agent."""

import json
import logging
import os
import sys
import time
import typing

import re_lay
from tools.execute import execute

def _load_dotenv():
    """Load agent-core/.env into os.environ without overriding existing vars."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

_load_dotenv()

logging.basicConfig(
    level=os.getenv("RECUR_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("re_cur")

# Dedicated signal stream for noise-free output
_signal = logging.getLogger("re_cur.signal")
_signal_handler = logging.StreamHandler()
_signal_handler.setFormatter(logging.Formatter(">> %(message)s"))
_signal.addHandler(_signal_handler)
_signal.propagate = False
_signal.setLevel(logging.INFO)

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
STATE_FILE = os.path.join(STATE_DIR, "messages.json")
STREAM_FILE = os.path.join(STATE_DIR, "stream.json")
MAX_NO_TOOL_TURNS = 3

_last_stream_write = 0.0

def _write_stream(data, force=False):
    """Write streaming state to disk, throttled to ~20 writes/sec."""
    global _last_stream_write
    now = time.monotonic()
    if not force and now - _last_stream_write < 0.05:
        return
    _last_stream_write = now
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STREAM_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, STREAM_FILE)

def _stream_callback(content, tool_calls, reasoning=None):
    _write_stream({"content": content, "tool_calls": tool_calls, "reasoning": reasoning, "done": False})
MAX_REPEATED_TOOL_TURNS = 4
# Approximate char budget for messages (rough: 1 token ≈ 4 chars).
# With -c 8192 and max_tokens=512, we have ~7680 tokens for input ≈ 30720 chars.
# We reserve some headroom.
MAX_HISTORY_CHARS = 25000
MAX_ITERATIONS = 200

SYSTEM_PROMPT = "DIRECTIVE: Minimize uncertainty about your environment."

def estimate_chars(messages):
    """Rough character count of the messages array."""
    total = 0
    for msg in messages:
        total += len(msg.get("content") or "")
        for tc in msg.get("tool_calls", []) or []:
            total += len(json.dumps(tc.get("function", {})))
    return total


def evict_oldest(messages):
    """Preserve the system message if present; evict oldest assistant+tool pairs."""
    start = 1 if messages and messages[0].get("role") == "system" else 0
    for i in range(start, len(messages)):
        if messages[i].get("role") == "assistant":
            # Remove this assistant and all subsequent tool messages until next assistant
            end = i + 1
            while end < len(messages) and messages[end].get("role") == "tool":
                end += 1
            removed = messages[i:end]
            del messages[i:end]
            logger.info("Evicted %d messages (indices %d-%d) to free context", len(removed), i, end - 1)
            return True
    return False


def persist_state(messages):
    """Write messages to disk."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def main():
    logger.info("=== re_cur engine starting ===")

    # Boot probe: run ls -la live and present the output as the first user message.
    # This gives the model its environmental context without injecting a synthetic
    # assistant tool call, which thinking models (e.g. Gemini 2.5) reject because
    # hand-crafted function calls lack the required thought_signature.
    boot_result = execute({
        "id": "boot-0",
        "type": "function",
        "function": {"name": "terminal", "arguments": json.dumps({"command": "ls -la"})},
    })
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[boot]\n$ ls -la\n{boot_result.get('content', '')}"},
    ]
    persist_state(messages)

    no_tool_count = 0
    repeated_tool_count = 0
    last_tool_signature = None
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        logger.info("--- Turn %d (messages: %d, ~%d chars) ---", iteration, len(messages), estimate_chars(messages))

        # Evict old messages if approaching context limit
        while estimate_chars(messages) > MAX_HISTORY_CHARS and len(messages) > 4:
            if not evict_oldest(messages):
                break

        # Send to LLM
        # Signal stream start
        _write_stream({"content": "", "tool_calls": [], "reasoning": "", "done": False}, force=True)
        response = re_lay.send_stream(messages, on_chunk=_stream_callback)

        if response.get("error"):
            err = response["error"]
            logger.error("LLM error on turn %d: %s", iteration, err)
            # JSON parse / truncation error — synthesize the failed turn in context
            # so the model sees a concrete error instead of regenerating blindly.
            if "parse_error" in err or "parse tool call" in err.lower() or "missing closing quote" in err.lower():
                err_id = f"err-{iteration}"
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": err_id,
                        "type": "function",
                        "function": {"name": "terminal", "arguments": "{}"},
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": err_id,
                    "content": (
                        "[Error: Your last response was truncated mid-generation — "
                        "the JSON tool call was incomplete. Do NOT include a 'thought' field. "
                        "Generate a short, complete tool call now.]"
                    ),
                })
                persist_state(messages)
                _write_stream({"done": True}, force=True)
                continue
            no_tool_count += 1
            if no_tool_count >= MAX_NO_TOOL_TURNS:
                logger.error("Circuit breaker: %d consecutive failures. Halting.", no_tool_count)
                _write_stream({"done": True}, force=True)
                sys.exit(1)
            _write_stream({"done": True}, force=True)
            continue

        # Build assistant message
        assistant_msg: dict[str, typing.Any] = {"role": "assistant"}
        content = response.get("content")
        tool_calls = response.get("tool_calls")
        reasoning = response.get("reasoning")

        if reasoning:
            assistant_msg["reasoning"] = reasoning
            _signal.info("[THINK] %s", reasoning[:300].replace('\n', '\\n'))

        if content:
            assistant_msg["content"] = content
            _signal.info("[THINK] %s", content[:300].replace('\n', '\\n'))
        else:
            assistant_msg["content"] = None

        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls

        if not tool_calls and not reasoning and content:
            assistant_msg["_thought"] = ("[Systematic internal trace: Plaintext reasoning] " + content[:200] + "...")

        messages.append(assistant_msg)
        persist_state(messages)
        _write_stream({"done": True}, force=True)

        if tool_calls:
            no_tool_count = 0
            
            current_signature_list = []

            # Execute each tool call and append results
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                
                # Extract thought and build clean display args
                display_args = args_str[:120]
                try:
                    args_dict = json.loads(args_str)
                    thought = args_dict.pop("thought", None)
                    if thought:
                        _signal.info("[THINK] %s", thought.replace('\n', '\\n'))
                        tc["_thought"] = thought
                    else:
                        tc["_thought"] = "[Systematic internal trace: Action executed without explicit thought parameter]"
                    # Clean display without thought field
                    display_args = json.dumps(args_dict, ensure_ascii=False)[:120]
                    # Rewrite the tool call arguments without thought to save context
                    func["arguments"] = json.dumps(args_dict, ensure_ascii=False)
                except Exception:
                    pass
                
                current_signature_list.append((func.get("name", ""), func.get("arguments", "")))
                
                _signal.info("[ACT] %s(%s)", func.get("name", "?").replace('\n', '\\n'), display_args.replace('\n', '\\n'))
                tool_result = execute(tc)
                _signal.info("[OBS] %s", tool_result.get("content", "")[:300].replace('\n', '\\n'))
                messages.append(tool_result)

            current_signature = tuple(current_signature_list)
            if current_signature == last_tool_signature:
                repeated_tool_count += 1
                if repeated_tool_count >= MAX_REPEATED_TOOL_TURNS:
                    logger.info("Circuit breaker: %d consecutive identical tool turns. Halting.", repeated_tool_count)
                    sys.exit(1)
            else:
                repeated_tool_count = 0
                last_tool_signature = current_signature
        else:
            # LLM produced text only (thinking out loud)
            no_tool_count += 1
            logger.info("No tool calls on turn %d (%d/%d). Content: %s",
                        iteration, no_tool_count, MAX_NO_TOOL_TURNS,
                        (content or "")[:200])

            messages.append({
                "role": "user",
                "content": "[System Error: No valid tool call detected. You must use one of the available functions (terminal, file_read, file_write) to interact with the environment. Please format your response as a valid tool call.]"
            })

            if no_tool_count >= MAX_NO_TOOL_TURNS:
                logger.info("Circuit breaker: %d consecutive no-tool turns. Halting.", no_tool_count)
                sys.exit(1)

        persist_state(messages)

    logger.info("=== re_cur engine stopped after %d turns ===", iteration)
    persist_state(messages)
    sys.exit(1)


if __name__ == "__main__":
    main()
