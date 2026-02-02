#!/usr/bin/env python3
"""
Setup CoreRag folder structure.

Creates the standard folders for inbox workflow and Obsidian integration.
"""

import os
from pathlib import Path


def setup_corerag_folders():
    """Create CoreRag folder structure."""
    
    # Get base directory from env or use default
    base_dir = Path(os.getenv("CoreRag_BASE_DIR", Path.home() / "Documents" / "CoreRag"))
    
    folders = {
        "inbox": base_dir / "Inbox",
        "processed": base_dir / "Processed",
        "obsidian": base_dir / "Obsidian",
        "obsidian_imports": base_dir / "Obsidian" / "CoreRag Imports",
    }
    
    print(f"Setting up CoreRag folders in: {base_dir}")
    print()
    
    for name, path in folders.items():
        if path.exists():
            print(f"✓ {name:20} already exists: {path}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            print(f"✓ {name:20} created: {path}")
    
    # Create .gitkeep in Inbox to preserve directory
    gitkeep = folders["inbox"] / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
    
    print()
    print("Environment variables to set:")
    print(f'export CORERAG_INBOX_DIR="{folders["inbox"]}"')
    print(f'export CoreRag_PROCESSED_DIR="{folders["processed"]}"')
    print(f'export CoreRag_OBSIDIAN_VAULT="{folders["obsidian"]}"')
    print(f'export CoreRag_WATCH_DIR="{folders["inbox"]}"')
    print()
    print("Folder setup complete!")


if __name__ == "__main__":
    setup_corerag_folders()
