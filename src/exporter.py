import hashlib
import logging
import os
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
    summary = metadata.get('summary', 'No summary provided.').replace('"', '\\"')

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

    # Generate backlinks from knowledge graph
    backlinks = _generate_backlinks(redacted_text, original_filename)
    if backlinks:
        note_content += backlinks

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


def _generate_backlinks(text: str, original_filename: str) -> str:
    """Generate Obsidian [[wikilinks]] based on shared entities in the knowledge graph."""
    try:
        from src.graph.knowledge_graph import KnowledgeGraph

        graph_db_path = Path(
            os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
        ).parent / "knowledge_graph.db"

        if not graph_db_path.exists():
            return ""

        graph = KnowledgeGraph(graph_db_path)

        # Compute document_id the same way executor.py does
        doc_id = hashlib.sha256(text[:5000].encode()).hexdigest()[:16]

        # Find documents sharing entities with this one
        related = graph.find_related_documents(doc_id, limit=20)
        if not related:
            return ""

        # Find existing vault files to link to
        ingested_dir = VAULT_PATH / "Ingested"
        if not ingested_dir.exists():
            return ""

        vault_files = {f.stem: f.stem for f in ingested_dir.glob("*.md")}
        if not vault_files:
            return ""

        # For each related document, try to find a matching vault file
        # Related docs have document_ids — we need to match against vault file content
        # Since we can't easily reverse the hash, use shared entities to find likely matches
        links = []
        original_stem = Path(original_filename).stem.lower()

        for rel in related:
            shared = rel.get("shared_entities", [])
            # Search vault files whose names contain any shared entity
            for entity in shared:
                entity_lower = entity.lower()
                for stem in vault_files:
                    if (
                        entity_lower in stem.lower()
                        and original_stem not in stem.lower()
                        and f"[[{stem}]]" not in links
                    ):
                        links.append(f"[[{stem}]]")
                        break

        if not links:
            return ""

        unique_links = list(dict.fromkeys(links))[:10]
        section = "\n\n---\n\n## Related Notes\n"
        section += "\n".join(f"- {link}" for link in unique_links)
        return section

    except Exception as e:
        logging.debug(f"Backlink generation skipped: {e}")
        return ""


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()
