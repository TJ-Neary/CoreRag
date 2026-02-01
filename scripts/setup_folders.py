#!/usr/bin/env python3
"""
Setup PKM folder structure.

Creates the standard folders for inbox workflow and Obsidian integration.
"""

import os
from pathlib import Path


def setup_pkm_folders():
    """Create PKM folder structure."""
    
    # Get base directory from env or use default
    base_dir = Path(os.getenv("PKM_BASE_DIR", Path.home() / "Documents" / "PKM"))
    
    folders = {
        "inbox": base_dir / "Inbox",
        "processed": base_dir / "Processed",
        "obsidian": base_dir / "Obsidian",
        "obsidian_imports": base_dir / "Obsidian" / "PKM Imports",
    }
    
    print(f"Setting up PKM folders in: {base_dir}")
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
    print(f'export PKM_INBOX_DIR="{folders["inbox"]}"')
    print(f'export PKM_PROCESSED_DIR="{folders["processed"]}"')
    print(f'export PKM_OBSIDIAN_VAULT="{folders["obsidian"]}"')
    print(f'export PKM_WATCH_DIR="{folders["inbox"]}"')
    print()
    print("Folder setup complete!")


if __name__ == "__main__":
    setup_pkm_folders()
