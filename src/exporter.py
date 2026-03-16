import logging
import re
from datetime import datetime
from pathlib import Path

from src.config import DB_PATH, VAULT_PATH, VAULT_PATHS

logger = logging.getLogger(__name__)


def export_to_vault(
    redacted_text: str, metadata: dict, original_filename: str, vault_name: str = "default"
):
    """
    Creates a Markdown file in the Obsidian Vault with YAML Frontmatter.
    """
    vault_path = VAULT_PATHS.get(vault_name, VAULT_PATH)
    if not vault_path.exists():
        logger.error(f"Vault path {vault_path} does not exist. Skipping export.")
        return

    # Construct Title
    year = metadata.get("year", "Unknown")
    doc_type = metadata.get("type", "Doc")
    sanitized_name = Path(original_filename).stem
    title = f"{year} - {doc_type} - {sanitized_name}"
    title = _sanitize_filename(title)

    # Metadata for YAML
    category = metadata.get("category", "Unsorted")
    summary = metadata.get("summary", "").replace('"', '\\"')
    if not summary:
        summary = "No summary available."
    is_sensitive = metadata.get("is_sensitive", False)

    # Build tag list: category + type + year + LLM collection tags
    tags = [category, doc_type, year]
    collection_tags = metadata.get("tags", [])
    if isinstance(collection_tags, str):
        collection_tags = [t.strip() for t in collection_tags.split(",") if t.strip()]
    for tag in collection_tags:
        if tag not in tags:
            tags.append(tag)
    tags_yaml = "\n".join(f"  - {t}" for t in tags if t and t != "Unknown")

    # Content heading — only say "Redacted" if actually sensitive
    content_heading = "Content (Redacted)" if is_sensitive else "Content"

    # YAML Frontmatter
    note_content = f"""---
date_processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
original_filename: "{original_filename}"
category: "{category}"
type: "{doc_type}"
year: "{year}"
is_sensitive: {str(is_sensitive).lower()}
tags:
{tags_yaml}
---

# {original_filename}

## Summary
{summary}

---

## {content_heading}
{redacted_text}
"""

    # Apply inline wikilinks and generate Related section
    note_content = _apply_backlinks(note_content, redacted_text, original_filename)

    # Destination in Vault
    dest_dir = vault_path / "Ingested"
    try:
        dest_dir.mkdir(exist_ok=True)
    except Exception as e:
        logger.error(f"Could not create Vault subfolder: {e}")
        dest_dir = vault_path

    dest_path = dest_dir / f"{title}.md"

    try:
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(note_content)
        logger.info(f"Exported clean note to Vault: {dest_path}")
    except Exception as e:
        logger.error(f"Failed to write to Vault: {e}")


def _apply_backlinks(note_content: str, text: str, original_filename: str) -> str:
    """Apply inline wikilinks and append Related Notes section."""
    try:
        from src.export.backlink_generator import BacklinkGenerator

        graph_db_path = DB_PATH.parent / "knowledge_graph.db"
        generator = BacklinkGenerator(VAULT_PATH, graph_db_path)

        # Apply inline wikilinks to content body (not frontmatter)
        current_stem = Path(original_filename).stem
        note_content = generator.apply_inline_links(note_content, exclude_stem=current_stem)

        # Generate Related Notes section from knowledge graph
        doc_id = BacklinkGenerator.compute_document_id(text)
        related_section = generator.generate_related_section(doc_id)
        if related_section:
            note_content += related_section

    except Exception as e:
        logger.debug(f"Backlink generation skipped: {e}")

    return note_content


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()
