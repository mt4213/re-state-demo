#!/usr/bin/env python3
with open('/sandbox/agent-core/re_cur.py') as f:
    content = f.read()
with open('/sandbox/workspace/full_recur.txt', 'w') as f:
    f.write(content)
print(f"Written {len(content)} chars")
