#!/usr/bin/env python3
import sys

src = open(sys.argv[1]).read()
start = src.find('def compress')
if start == -1:
    print("NOT FOUND")
    sys.exit(1)
# Find the next top-level def or end of file
rest = src[start+1:]
indent = None
lines = [src[start:]]
for line in rest.split('\n'):
    stripped = line.lstrip()
    if not stripped or stripped.startswith('#') or (line.startswith(' ') and not stripped.startswith('#')):
        lines.append(line)
    elif line.strip() and not line[0].isspace():
        break
    else:
        lines.append(line)
print(''.join(lines))
