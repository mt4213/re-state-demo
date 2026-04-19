#!/usr/bin/env python3
"""Analyze re_cur.py for crash recovery and compress references."""

with open('/sandbox/agent-core/re_cur.py') as f:
    lines = f.readlines()

results = {
    'total_lines': len(lines),
    'compress_mentions': [],
    'crash_recovery_code': [],
    'import_section': [],
    'main_loop_section': [],
    'load_state_section': [],
}

in_import = False
in_main = False
in_crash_recovery = False

for i, line in enumerate(lines):
    # Track imports
    if i < 30:
        results['import_section'].append((i+1, line.rstrip()))
    
    # Check for compress
    if 'compress' in line.lower():
        results['compress_mentions'].append((i+1, line.rstrip()))
    
    # Check for crash recovery
    if 'crash' in line.lower() or 'recover' in line.lower() or 'resume' in line.lower():
        results['crash_recovery_code'].append((i+1, line.rstrip()))
    
    # Find load_state and main loop
    if 'def load_state' in line or 'def persist_state' in line or 'def main' in line:
        results['main_loop_section'].append((i+1, line.rstrip()))
    
    # Track state loading
    if 'STATE_FILE' in line or 'messages.json' in line:
        results['load_state_section'].append((i+1, line.rstrip()))

with open('/sandbox/workspace/analysis.txt', 'w') as f:
    f.write("=== IMPORT SECTION ===\n")
    for ln, text in results['import_section']:
        f.write(f"L{ln}: {text}\n")
    
    f.write("\n=== COMPRESS MENTIONS ===\n")
    if results['compress_mentions']:
        for ln, text in results['compress_mentions']:
            f.write(f"L{ln}: {text}\n")
    else:
        f.write("(none found)\n")
    
    f.write("\n=== CRASH RECOVERY CODE ===\n")
    for ln, text in results['crash_recovery_code']:
        f.write(f"L{ln}: {text}\n")
    
    f.write("\n=== KEY FUNCTIONS ===\n")
    for ln, text in results['main_loop_section']:
        f.write(f"L{ln}: {text}\n")
    
    f.write("\n=== STATE FILE REFERENCES ===\n")
    for ln, text in results['load_state_section']:
        f.write(f"L{ln}: {text}\n")
    
    f.write(f"\nTotal lines: {results['total_lines']}\n")

print("Analysis written to /sandbox/workspace/analysis.txt")
