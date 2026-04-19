#!/usr/bin/env python3
with open('/sandbox/agent-core/re_cur.py') as f:
    lines = f.readlines()

# Find the main function
in_main = False
main_lines = []
for i, l in enumerate(lines):
    if 'def main():' in l:
        in_main = True
    if in_main:
        main_lines.append(l)
        if l.strip() == '' and main_lines and main_lines[-2].strip().startswith('sys.exit'):
            break

with open('/sandbox/workspace/main_code.txt', 'w') as f:
    for line in main_lines:
        f.write(line)

print(f"Written {len(main_lines)} lines")
