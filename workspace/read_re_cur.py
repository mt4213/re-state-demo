#!/usr/bin/env python3
with open('/sandbox/agent-core/re_cur.py') as f:
    content = f.read()
with open('/sandbox/workspace/re_cur_full.txt', 'w') as f:
    f.write(content)
print(f"Total: {len(content)} chars, {content.count(chr(10))} lines")
