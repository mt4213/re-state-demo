#!/usr/bin/env python3
"""Extract the compress function from re_cur.py"""
import sys

src_file = '/sandbox/agent-core/re_cur.py'
out_file = '/sandbox/workspace/compress_func.txt'

with open(src_file, 'r') as f:
    lines = f.readlines()

# Find the compress function
start_idx = None
for i, line in enumerate(lines):
    if line.strip().startswith('def compress'):
        start_idx = i
        break

if start_idx is None:
    with open(out_file, 'w') as f:
        f.write("NOT FOUND\n")
    sys.exit(0)

# Find the end of the function (next top-level def or end)
end_idx = len(lines)
for i in range(start_idx + 1, len(lines)):
    if lines[i].startswith('def ') or lines[i].startswith('class '):
        end_idx = i
        break

# Write the compress function
with open(out_file, 'w') as f:
    f.writelines(lines[start_idx:end_idx])
    
print(f"Extracted lines {start_idx+1} to {end_idx} to {out_file}")
