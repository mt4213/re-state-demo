#!/usr/bin/env python3
"""Extract the main() function from re_cur.py into a separate file."""

with open('/sandbox/agent-core/re_cur.py') as f:
    lines = f.readlines()

# Find the main function
start_line = None
end_line = len(lines)
indent_level = None

for i, line in enumerate(lines):
    if line.strip().startswith('def main():'):
        start_line = i
        # The indentation level of 'def main' is 0 (it's at module level)
        indent_level = 0
        break

if start_line is None:
    print("main() not found")
    exit(1)

# Now collect all lines at indent level 0 until end of file
main_lines = [lines[start_line]]
for i in range(start_line + 1, len(lines)):
    line = lines[i]
    # A new top-level function starts with no indentation and 'def '
    if line.strip().startswith('def ') and not line[0].isspace():
        break
    main_lines.append(line)

with open('/sandbox/workspace/main_extracted.py', 'w') as f:
    f.writelines(main_lines)

print(f"Extracted {len(main_lines)} lines from re_cur.py (lines {start_line+1}-{start_line+len(main_lines)})")
