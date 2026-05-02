#!/usr/bin/env python3
"""Trace a single ContReAct agent turn: state -> LLM query -> response."""

import os
import sys
import json
import logging

sys.path.insert(0, '/home/user_a/projects/sandbox/agent-core')

from re_cur import STATE_FILE, STREAM_FILE, get_timestamp
from re_lay import lay  # the LLM router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("__main__")

def trace_turn():
    """Read current state, construct LLM query, log response."""
    # 1. Load state
    if not os.path.exists(STATE_FILE):
        logger.error("%s not found. Run agent first or create state/ directory.", STATE_FILE)
        sys.exit(1)
    
    with open(STATE_FILE, 'r') as f:
        state = json.load(f)
    
    messages = state.get('messages', [])
    if not messages:
        logger.error("No messages in state. Agent may be new.")
        return
    
    logger.info("=== TRACE TURN %d ===", len(messages))
    
    # 2. Extract current LLM prompt (last 'user' or 'system' message)
    last_prompt = None
    for m in reversed(messages):
        if m.get('role') in ('user', 'system', 'assistant'):
            content = m.get('content')
            if content:
                last_prompt = content
                break
    
    if last_prompt:
        logger.info("LLM Prompt (last turn):")
        logger.info("-" * 60)
        print(last_prompt[:500])  # preview
        logger.info("-" * 60)
    else:
        logger.info("No natural language prompt detected in messages.")
    
    # 3. Load tools (from re_lay)
    from re_lay import TOOLS
    logger.info("Available tools: %s", [t['name'] for t in TOOLS])
    
    # 4. Try LLM call (if configured)
    try:
        logger.info("Attempting LLM call...")
        response = lay(last_prompt, tools=TOOLS)
        logger.info("Response type: %s", type(response).__name__)
        
        if isinstance(response, dict) and response.get('role') == 'assistant':
            # Natural language
            content = response.get('content', '')
            logger.info("LLM Response (first 300 chars):")
            logger.info("-" * 60)
            print(content[:300])
            logger.info("-" * 60)
        elif 'tool_calls' in response:
            # Tool call
            tool_calls = response.get('tool_calls', [])
            logger.info("Tool calls detected: %d", len(tool_calls))
            for tc in tool_calls:
                name = tc.get('function', {}).get('name', '')
                args = tc.get('function', {}).get('arguments', '{}')
                logger.info("  %s: %s", name, args[:100])
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
    
    logger.info("=== END TURN ===")

if __name__ == "__main__":
    trace_turn()
