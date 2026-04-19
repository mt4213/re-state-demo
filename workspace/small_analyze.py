#!/usr/bin/env python3
with open('/sandbox/agent-core/re_cur.py') as f:
    lines = f.readlines()
with open('/sandbox/workspace/analysis_small.txt', 'w') as f:
    f.write(f"Total lines: {len(lines)}\n\n")
    
    # Find lines with 'compress'
    compress_lines = [(i+1, l.rstrip()) for i, l in enumerate(lines) if 'compress' in l.lower()]
    f.write(f"Lines with 'compress': {len(compress_lines)}\n")
    for ln, text in compress_lines:
        f.write(f"L{ln}: {text}\n")
    
    # Find lines with 'crash' or 'recover' or 'resume'
    recovery_lines = [(i+1, l.rstrip()) for i, l in enumerate(lines) if 'crash' in l.lower() or 'recover' in l.lower() or 'resume' in l.lower()]
    f.write(f"\nLines with crash/recover/resume: {len(recovery_lines)}\n")
    for ln, text in recovery_lines:
        f.write(f"L{ln}: {text}\n")
    
    # Find key function definitions
    f.write("\n\nKey functions:\n")
    for i, l in enumerate(lines):
        if l.strip().startswith('def '):
            f.write(f"L{i+1}: {l.strip()}\n")

print("Done")