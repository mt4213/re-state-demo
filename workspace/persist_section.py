#!/usr/bin/env python3
with open('/sandbox/agent-core/re_cur.py') as f:
    lines = f.readlines()

# Find persist_state function
in_persist = False
persist_lines = []
for i, line in enumerate(lines):
    if 'def persist_state(' in line:
        in_persist = True
    if in_persist:
        persist_lines.append(line)
        # Function ends when we hit another top-level def or dedented to module level
        if line.strip().startswith('def ') and 'def persist_state(' not in line:
            break
        if line.strip() == '' and persist_lines and not lines[i-1].strip():
            break

with open('/sandbox/workspace/persist_section.txt', 'w') as f:
    f.writelines(persist_lines)

print(f"persist_state: {len(persist_lines)} lines")
