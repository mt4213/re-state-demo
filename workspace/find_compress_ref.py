#!/usr/bin/env python3
"""Find references to 'compress' in re_cur.py and extract surrounding context."""

src_file = '/sandbox/agent-core/re_cur.py'
out_file = '/sandbox/workspace/compress_refs.txt'

with open(src_file, 'r') as f:
    lines = f.readlines()

results = []
for i, line in enumerate(lines, 1):
    if 'compress' in line.lower():
        # Capture context: 3 lines before and after
        start = max(0, i - 4)
        end = min(len(lines), i + 2)
        results.append(f"--- Line {i} ---")
        results.extend(lines[start:end])
        results.append("")

with open(out_file, 'w') as f:
    f.writelines(results)

print(f"Found {len(results)} matching lines, written to {out_file}")
