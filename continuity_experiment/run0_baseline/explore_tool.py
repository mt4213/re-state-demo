#!/usr/bin/env python3
"""
Environment Exploration Tool

Creates a detailed tree view of directories and files, 
including file sizes and types to help an autonomous agent
understand its environment and minimize uncertainty.
"""

import os
import sys
import stat
from pathlib import Path
from typing import List, Tuple, Optional

class ExplorationReport:
    """Structured report of explored environment."""
    
    def __init__(self):
        self.path: str = ""
        self.files: List[dict] = []
        self.directories: List[dict] = []
        self.total_size: int = 0
        self.file_count: int = 0
        self.dir_count: int = 0
        self.permissions: dict = {}
    
    def add_file(self, name: str, size: int, mode: int, is_executable: bool):
        self.files.append({
            'name': name,
            'size': size,
            'mode': mode,
            'executable': is_executable
        })
        self.total_size += size
        self.file_count += 1
    
    def add_directory(self, name: str, items: List[str]):
        self.directories.append({
            'name': name,
            'items': items
        })
        self.dir_count += 1
    
    def __str__(self) -> str:
        lines = []
        lines.append(f"📁 Path: {self.path}")
        lines.append(f"📊 Summary: {self.dir_count} dirs, {self.file_count} files, "
                     f"{self.total_size / 1024:.1f} KB")
        lines.append(f"📋 Executable files: {[f['name'] for f in self.files if f['executable']]}")
        return "\n".join(lines)


def get_file_info(path: str) -> Tuple[int, int, bool]:
    """Get file size, mode, and if it's executable."""
    try:
        st = os.stat(path)
        size = st.st_size
        mode = stat.S_IMODE(st.st_mode)
        is_exec = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        return size, mode, is_exec
    except (OSError, IOError):
        return 0, 0, False


def explore_tree(path: str, max_depth: int = 3) -> ExplorationReport:
    """Recursively explore directory tree with depth limit."""
    report = ExplorationReport()
    report.path = os.path.abspath(path)
    
    try:
        items = sorted(os.listdir(path))
    except PermissionError:
        print(f"❌ Permission denied: {path}")
        return report
    except FileNotFoundError:
        print(f"❌ Path not found: {path}")
        return report
    
    for i, item in enumerate(items):
        full_path = os.path.join(path, item)
        is_last = i == len(items) - 1
        
        if os.path.isdir(full_path):
            prefix = "└── " if is_last else "├── "
            print(f"{prefix}{item}/")
            
            if max_depth > 0:
                report.add_directory(item, items)
                sub_report = explore_tree(full_path, max_depth - 1)
                report.total_size += sub_report.total_size
                report.file_count += sub_report.file_count
                report.dir_count += sub_report.dir_count
                for f in sub_report.files:
                    report.files.append(f)
        else:
            prefix = "    " if is_last else "│   "
            size, mode, is_exec = get_file_info(full_path)
            print(f"{prefix}📄 {item} {size / 1024:.1f} KB{' (executable)' if is_exec else ''}")
            report.add_file(item, size, mode, is_exec)
    
    return report


def main():
    """Main entry point for exploration tool."""
    print("🔍 Environment Exploration Tool")
    print("=" * 50)
    
    # Default to current working directory
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    # Ask for exploration depth
    default_depth = 2
    print(f"Default exploration depth: {default_depth}")
    
    report = explore_tree(path, max_depth=default_depth)
    
    print("\n" + "=" * 50)
    print(report)
    
    # Exit codes for automation
    if not report.files:
        print("\n⚠️  No files found in explored directories.")
        sys.exit(1)
    else:
        print(f"\n✅ Exploration complete. Found {len(report.files)} files.")
        sys.exit(0)


if __name__ == "__main__":
    main()
