"""
Export content to Obsidian vault.

Handles creating markdown files with proper frontmatter and formatting
for Obsidian compatibility.
"""

import os
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ObsidianExporter:
    """Exports content to an Obsidian vault."""

    def __init__(self, vault_path: Optional[Path] = None):
        """
        Initialize exporter.
        
        Args:
            vault_path: Path to Obsidian vault root. If None, uses PKM_OBSIDIAN_VAULT env var.
        """
        self.vault_path = vault_path
        if not self.vault_path:
            env_path = os.getenv("PKM_OBSIDIAN_VAULT")
            if env_path:
                self.vault_path = Path(env_path)
        
        if self.vault_path:
            self.imports_dir = self.vault_path / "PKM Imports"
        else:
            self.imports_dir = None

    def export_to_vault(self, source_path: Path, content: str, metadata: Dict[str, Any]) -> Optional[Path]:
        """
        Create markdown file in Obsidian vault.
        
        Args:
            source_path: Path to the original source file
            content: Text content to export
            metadata: Metadata dictionary to include in frontmatter
            
        Returns:
            Path to the created markdown file, or None if export disabled/failed
        """
        if not self.vault_path or not self.imports_dir:
            logger.debug("Obsidian export skipped: Vault path not configured")
            return None

        # Check if export is enabled
        if os.getenv("PKM_EXPORT_TO_OBSIDIAN", "true").lower() != "true":
            return None

        try:
            # Ensure imports directory exists
            self.imports_dir.mkdir(parents=True, exist_ok=True)
            
            # Format content with frontmatter
            md_content = self._format_as_obsidian(source_path, content, metadata)
            
            # Create destination filename (sanitize to fail-safe)
            safe_name = self._sanitize_filename(source_path.stem)
            md_path = self.imports_dir / f"{safe_name}.md"
            
            # Write file
            md_path.write_text(md_content, encoding="utf-8")
            logger.info(f"Exported to Obsidian: {md_path}")
            
            return md_path
            
        except Exception as e:
            logger.error(f"Failed to export to Obsidian: {e}")
            return None

    def _format_as_obsidian(self, source_path: Path, content: str, metadata: Dict[str, Any]) -> str:
        """Format content with Obsidian-compatible frontmatter."""
        # Clean up metadata for frontmatter
        frontmatter = {
            "source_file": source_path.name,
            "source_path": str(source_path),
            "ingested_at": datetime.now().isoformat(),
            "type": "pkm_import",
            "tags": ["pkm/import"]
        }
        
        # Add file type specific tags
        file_type = metadata.get("file_type", "unknown")
        if file_type:
            frontmatter["tags"].append(f"type/{file_type}")
            
        # Basic YAML generation
        yaml_lines = ["---"]
        for key, value in frontmatter.items():
            if isinstance(value, list):
                yaml_lines.append(f"{key}:")
                for item in value:
                    yaml_lines.append(f"  - {item}")
            else:
                yaml_lines.append(f"{key}: {value}")
        yaml_lines.append("---")
        
        # Add source link header
        header = f"\n# Imported: {source_path.name}\n\n"
        
        return "\n".join(yaml_lines) + header + content

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for compatibility."""
        # Replace problematic chars with underscore
        safe = re.sub(r'[\\/*?:"<>|]', '_', filename)
        return safe
