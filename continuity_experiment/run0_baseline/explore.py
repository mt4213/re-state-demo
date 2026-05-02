#!/usr/bin/env python3
"""File explorer utility - builds a tree view of a directory."""
import os
import sys
from pathlib import Path

def walk_tree(root_path: str, max_depth: int = 10, show_hidden: bool = True) -> list:
    """Generate a tree representation of a directory.
    
    Args:
        root_path: Path to start walking from
        max_depth: Maximum depth to traverse
        show_hidden: Whether to show hidden files (starting with .)
        
    Returns:
        List of strings representing the tree structure
    """
    result = []
    root = Path(root_path)
    if not root.exists():
        return [f"Error: {root_path} does not exist"]
    
    def _indent(depth):
        return "  " * depth
    
    def _walk(path, depth, prefix=""):
        if depth > max_depth:
            return
            
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.name.startswith('.'), p))
        except PermissionError:
            return
            
        for entry in entries:
            if not show_hidden and entry.name.startswith('.'):
                continue
                
            if depth == max_depth:
                # Show only file count or first N items
                if entry.is_dir():
                    try:
                        count = len(list(entry.iterdir()))
                        result.append(_indent(depth) + f"{entry.name}/ ({count})")
                    except:
                        result.append(_indent(depth) + entry.name)
                else:
                    result.append(_indent(depth) + entry.name)
                continue
                
            display_name = entry.name
            if entry.is_dir():
                result.append(_indent(depth) + f"{display_name}/")
                _walk(entry, depth + 1, "")
            else:
                result.append(_indent(depth) + display_name)
    
    _walk(root, 0)
    return result

def main():
    """Command-line interface."""
    if len(sys.argv) < 2:
        print("Usage: python explore.py <directory> [max_depth] [show_hidden]")
        print("  max_depth (default 10): Maximum directory depth")
        print("  show_hidden (default 1): 1=show, 0=hide files starting with '.'")
        sys.exit(1)
    
    target = Path(sys.argv[1])
    max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    show_hidden = sys.argv[3] == "0" if len(sys.argv) > 3 else True
    
    tree = walk_tree(str(target), max_depth, show_hidden)
    for line in tree:
        print(line)

if __name__ == "__main__":
    main()
