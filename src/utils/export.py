"""
Export capabilities for CoreRag.

Export knowledge base data in various formats.
"""

import csv
import json
import logging
import zipfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import shutil

logger = logging.getLogger(__name__)


class ExportFormat:
    """Supported export formats."""
    JSON = "json"
    CSV = "csv"
    MARKDOWN = "markdown"
    OBSIDIAN = "obsidian"
    HTML = "html"
    SQLITE = "sqlite"
    ZIP_BUNDLE = "zip"


class Exporter:
    """
    Export CoreRag data in various formats.

    Supports full exports, filtered exports, and incremental exports.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        export_dir: Optional[Path] = None
    ):
        """
        Initialize exporter.

        Args:
            data_dir: CoreRag data directory
            export_dir: Directory for exports
        """
        self.data_dir = data_dir or Path.home() / ".corerag" / "data"
        self.export_dir = export_dir or Path.home() / ".corerag" / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_all(
        self,
        format: str = ExportFormat.ZIP_BUNDLE,
        include_embeddings: bool = False
    ) -> Path:
        """
        Export entire knowledge base.

        Args:
            format: Export format
            include_embeddings: Include vector embeddings (large!)

        Returns:
            Path to exported file/directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"corerag_export_{timestamp}"

        if format == ExportFormat.ZIP_BUNDLE:
            return self._export_zip_bundle(export_name, include_embeddings)
        elif format == ExportFormat.JSON:
            return self._export_json(export_name)
        elif format == ExportFormat.MARKDOWN:
            return self._export_markdown(export_name)
        elif format == ExportFormat.OBSIDIAN:
            return self._export_obsidian(export_name)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def export_search_results(
        self,
        results: List[Dict],
        format: str = ExportFormat.MARKDOWN,
        filename: Optional[str] = None
    ) -> Path:
        """
        Export search results.

        Args:
            results: Search results to export
            format: Export format
            filename: Optional custom filename

        Returns:
            Path to exported file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"search_results_{timestamp}"

        if format == ExportFormat.MARKDOWN:
            return self._export_results_markdown(results, filename)
        elif format == ExportFormat.JSON:
            return self._export_results_json(results, filename)
        elif format == ExportFormat.CSV:
            return self._export_results_csv(results, filename)
        elif format == ExportFormat.HTML:
            return self._export_results_html(results, filename)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def export_documents(
        self,
        document_ids: List[str],
        format: str = ExportFormat.MARKDOWN,
        include_chunks: bool = True
    ) -> Path:
        """
        Export specific documents.

        Args:
            document_ids: Documents to export
            format: Export format
            include_chunks: Include individual chunks

        Returns:
            Path to export
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"documents_{timestamp}"

        # Load documents (placeholder - real implementation would query DB)
        documents = self._load_documents(document_ids)

        if format == ExportFormat.MARKDOWN:
            return self._export_docs_markdown(documents, export_name, include_chunks)
        elif format == ExportFormat.JSON:
            return self._export_docs_json(documents, export_name)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def export_metadata(self) -> Path:
        """Export all document metadata (without content)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = self.export_dir / f"metadata_{timestamp}.json"

        # Placeholder - real implementation would query DB
        metadata = self._get_all_metadata()

        with open(export_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.info(f"Exported metadata to {export_path}")
        return export_path

    def export_for_backup(self) -> Path:
        """
        Create a complete backup export.

        Includes everything needed to restore the system.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.export_dir / f"backup_{timestamp}.zip"

        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Export database
            if (self.data_dir / "lancedb").exists():
                for file in (self.data_dir / "lancedb").rglob("*"):
                    if file.is_file():
                        arcname = f"lancedb/{file.relative_to(self.data_dir / 'lancedb')}"
                        zf.write(file, arcname)

            # Export state files
            state_dir = self.data_dir.parent / "state"
            if state_dir.exists():
                for file in state_dir.rglob("*.json"):
                    arcname = f"state/{file.relative_to(state_dir)}"
                    zf.write(file, arcname)

            # Export config
            config_file = self.data_dir.parent / "config.json"
            if config_file.exists():
                zf.write(config_file, "config.json")

            # Add manifest
            manifest = {
                "exported_at": datetime.now().isoformat(),
                "version": "1.0",
                "components": ["lancedb", "state", "config"]
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        logger.info(f"Created backup at {backup_path}")
        return backup_path

    def _export_zip_bundle(self, name: str, include_embeddings: bool) -> Path:
        """Create ZIP bundle export."""
        bundle_path = self.export_dir / f"{name}.zip"

        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Export as JSON
            documents = self._get_all_documents(include_embeddings)

            zf.writestr(
                "documents.json",
                json.dumps(documents, indent=2, default=str)
            )

            # Export metadata separately
            zf.writestr(
                "metadata.json",
                json.dumps(self._get_all_metadata(), indent=2, default=str)
            )

            # Add export info
            info = {
                "exported_at": datetime.now().isoformat(),
                "document_count": len(documents),
                "includes_embeddings": include_embeddings
            }
            zf.writestr("export_info.json", json.dumps(info, indent=2))

        return bundle_path

    def _export_json(self, name: str) -> Path:
        """Export as JSON file."""
        export_path = self.export_dir / f"{name}.json"

        data = {
            "exported_at": datetime.now().isoformat(),
            "documents": self._get_all_documents(include_embeddings=False),
            "metadata": self._get_all_metadata()
        }

        with open(export_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return export_path

    def _export_markdown(self, name: str) -> Path:
        """Export as Markdown files."""
        export_dir = self.export_dir / name
        export_dir.mkdir(exist_ok=True)

        documents = self._get_all_documents(include_embeddings=False)

        for doc in documents:
            doc_file = export_dir / f"{doc['id']}.md"

            content = [
                f"# {doc.get('title', 'Untitled')}",
                "",
                f"**Source**: {doc.get('source_path', 'Unknown')}",
                f"**Created**: {doc.get('created_at', 'Unknown')}",
                f"**Tags**: {', '.join(doc.get('tags', []))}",
                "",
                "---",
                "",
                doc.get('content', '')
            ]

            doc_file.write_text("\n".join(content))

        # Create index
        index_content = ["# CoreRag Export", "", f"Exported: {datetime.now().isoformat()}", ""]
        for doc in documents:
            index_content.append(f"- [{doc.get('title', doc['id'])}]({doc['id']}.md)")

        (export_dir / "index.md").write_text("\n".join(index_content))

        return export_dir

    def _export_obsidian(self, name: str) -> Path:
        """Export in Obsidian vault format."""
        vault_dir = self.export_dir / name
        vault_dir.mkdir(exist_ok=True)

        documents = self._get_all_documents(include_embeddings=False)

        for doc in documents:
            # Create folder structure based on source path
            source_path = doc.get('source_path', '')
            if source_path:
                relative_path = Path(source_path).parent.name
                doc_dir = vault_dir / relative_path
                doc_dir.mkdir(exist_ok=True)
            else:
                doc_dir = vault_dir

            doc_file = doc_dir / f"{doc.get('title', doc['id'])}.md"

            # Obsidian YAML frontmatter
            frontmatter = [
                "---",
                f"id: {doc['id']}",
                f"source: \"{doc.get('source_path', '')}\"",
                f"created: {doc.get('created_at', '')}",
                f"tags: [{', '.join(doc.get('tags', []))}]",
                "---",
                ""
            ]

            content = frontmatter + [doc.get('content', '')]
            doc_file.write_text("\n".join(content))

        return vault_dir

    def _export_results_markdown(self, results: List[Dict], filename: str) -> Path:
        """Export search results as Markdown."""
        export_path = self.export_dir / f"{filename}.md"

        lines = [
            "# Search Results",
            "",
            f"Exported: {datetime.now().isoformat()}",
            f"Results: {len(results)}",
            "",
            "---",
            ""
        ]

        for i, result in enumerate(results, 1):
            lines.extend([
                f"## {i}. {result.get('title', 'Untitled')}",
                "",
                f"**Score**: {result.get('score', 0):.2f}",
                f"**Source**: {result.get('source_path', 'Unknown')}",
                "",
                f"> {result.get('snippet', '')[:500]}...",
                "",
                "---",
                ""
            ])

        export_path.write_text("\n".join(lines))
        return export_path

    def _export_results_json(self, results: List[Dict], filename: str) -> Path:
        """Export search results as JSON."""
        export_path = self.export_dir / f"{filename}.json"

        data = {
            "exported_at": datetime.now().isoformat(),
            "result_count": len(results),
            "results": results
        }

        with open(export_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return export_path

    def _export_results_csv(self, results: List[Dict], filename: str) -> Path:
        """Export search results as CSV."""
        export_path = self.export_dir / f"{filename}.csv"

        if not results:
            export_path.write_text("")
            return export_path

        fieldnames = ["rank", "title", "score", "source_path", "snippet"]

        with open(export_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for i, result in enumerate(results, 1):
                writer.writerow({
                    "rank": i,
                    "title": result.get("title", ""),
                    "score": result.get("score", 0),
                    "source_path": result.get("source_path", ""),
                    "snippet": result.get("snippet", "")[:200]
                })

        return export_path

    def _export_results_html(self, results: List[Dict], filename: str) -> Path:
        """Export search results as HTML."""
        export_path = self.export_dir / f"{filename}.html"

        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "  <title>CoreRag Search Results</title>",
            "  <style>",
            "    body { font-family: system-ui; max-width: 800px; margin: 0 auto; padding: 20px; }",
            "    .result { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 8px; }",
            "    .title { font-size: 1.2em; font-weight: bold; }",
            "    .score { color: #666; }",
            "    .snippet { margin-top: 10px; color: #333; }",
            "    .source { font-size: 0.9em; color: #888; }",
            "  </style>",
            "</head>",
            "<body>",
            f"  <h1>Search Results ({len(results)})</h1>",
        ]

        for result in results:
            html.extend([
                "  <div class='result'>",
                f"    <div class='title'>{result.get('title', 'Untitled')}</div>",
                f"    <div class='score'>Score: {result.get('score', 0):.2f}</div>",
                f"    <div class='snippet'>{result.get('snippet', '')[:300]}...</div>",
                f"    <div class='source'>Source: {result.get('source_path', 'Unknown')}</div>",
                "  </div>"
            ])

        html.extend([
            "</body>",
            "</html>"
        ])

        export_path.write_text("\n".join(html))
        return export_path

    # Placeholder methods - real implementation would query database
    def _get_all_documents(self, include_embeddings: bool = False) -> List[Dict]:
        """Get all documents from database."""
        # Placeholder - real implementation would query LanceDB
        return []

    def _get_all_metadata(self) -> Dict:
        """Get all metadata from database."""
        # Placeholder
        return {"document_count": 0, "last_updated": datetime.now().isoformat()}

    def _load_documents(self, document_ids: List[str]) -> List[Dict]:
        """Load specific documents."""
        # Placeholder
        return []

    def _export_docs_markdown(self, documents: List[Dict], name: str, include_chunks: bool) -> Path:
        """Export documents as Markdown."""
        export_dir = self.export_dir / name
        export_dir.mkdir(exist_ok=True)

        for doc in documents:
            doc_file = export_dir / f"{doc.get('id', 'unknown')}.md"
            doc_file.write_text(doc.get('content', ''))

        return export_dir

    def _export_docs_json(self, documents: List[Dict], name: str) -> Path:
        """Export documents as JSON."""
        export_path = self.export_dir / f"{name}.json"

        with open(export_path, "w") as f:
            json.dump(documents, f, indent=2, default=str)

        return export_path
