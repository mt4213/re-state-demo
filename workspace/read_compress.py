import sys
in_compress = False
for line in sys.stdin:
    if line.startswith('def compress'):
        in_compress = True
    if in_compress:
        print(line, end='')
        if line.strip() and not line.startswith(' ') and not line.startswith('\t') and in_compress and 'def compress' not in line:
            break
        # stop at next function definition at module level
        if in_compress and line.startswith('def ') and 'def compress' not in line:
            break
