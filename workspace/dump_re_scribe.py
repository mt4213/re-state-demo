#!/usr/bin/env python3
with open('/sandbox/agent-core/re_scribe.py') as f:
    content = f.read()
with open('/sandbox/workspace/re_scribe_full.txt', 'w') as f:
    f.write(content)
print(f"Written {len(content)} chars")
