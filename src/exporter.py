import logging
import re
from pathlib import Path
from datetime import datetime
from src.config import VAULT_PATH

def export_to_vault(redacted_text: str, metadata: dict, original_filename: str):
    """
    Creates a Markdown file in the Obsidian Vault with YAML Frontmatter.
    """
    if not VAULT_PATH.exists():
        logging.error(f"Vault path {VAULT_PATH} does not exist. Skipping export.")
        return

    # Construct Title
    year = metadata.get('year', 'Unknown')
    doc_type = metadata.get('type', 'Doc')
    sanitized_name = Path(original_filename).stem
    title = f"{year} - {doc_type} - {sanitized_name}"
    title = _sanitize_filename(title)
    
    # Metadata for YAML
    category = metadata.get('category', 'Unsorted')
    summary = metadata.get('summary', 'No summary provided.').replace('"', '\\"') # Escape quotes

    # YAML Frontmatter
    note_content = f"""---
date_processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
original_filename: "{original_filename}"
category: "{category}"
type: "{doc_type}"
year: "{year}"
tags:
  - {category}
  - {doc_type}
  - {year}
---

# {original_filename}

## Summary
{summary}

---

## Content (Redacted)
{redacted_text}
"""
    
    # Destination in Vault
    dest_dir = VAULT_PATH / "Ingested"
    try:
        dest_dir.mkdir(exist_ok=True)
    except Exception as e:
        logging.error(f"Could not create Vault subfolder: {e}")
        dest_dir = VAULT_PATH

    dest_path = dest_dir / f"{title}.md"
    
    try:
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(note_content)
        logging.info(f"Exported clean note to Vault: {dest_path}")
    except Exception as e:
        logging.error(f"Failed to write to Vault: {e}")

def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()
