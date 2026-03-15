"""Maintenance tool group — versioning, vaults, integrations, reindexing."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MaintenanceTools:
    """Maintenance and operations tools."""

    def __init__(self, db=None, vault_root=None):
        self.db = db
        self.vault_root = vault_root or Path.cwd()

    async def trigger_reindex(
        self, path: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        """Trigger re-indexing of files in the vault."""
        try:
            from src.utils.checkpoint import CheckpointManager

            scan_path = Path(path) if path else self.vault_root
            if not scan_path.exists():
                return {"error": f"Path not found: {scan_path}"}

            supported_exts = {
                ".md",
                ".txt",
                ".pdf",
                ".docx",
                ".json",
                ".yaml",
                ".csv",
                ".log",
                ".png",
                ".jpg",
                ".jpeg",
                ".tiff",
                ".webp",
                ".bmp",
                ".heic",
                ".py",
                ".js",
                ".ts",
                ".jsx",
                ".tsx",
                ".go",
                ".rs",
                ".java",
                ".rb",
            }
            files = []
            if scan_path.is_file():
                files = [scan_path]
            else:
                for f in scan_path.rglob("*"):
                    if f.is_file() and f.suffix.lower() in supported_exts:
                        files.append(f)

            if not files:
                return {
                    "status": "no_files",
                    "path": str(scan_path),
                    "message": "No indexable files found",
                }

            if not force and self.db:
                try:
                    child_table = self.db.open_table("child_chunks")
                    indexed = {
                        r["source_path"]
                        for r in child_table.search()
                        .select(["source_path"])
                        .limit(100000)
                        .to_list()
                    }
                    files = [f for f in files if f.name not in indexed]
                except Exception:
                    pass

            cm = CheckpointManager()
            job = cm.create_job("reindex", files, config={"force": force, "path": str(scan_path)})

            return {
                "status": "queued",
                "job_id": job.job_id,
                "total_files": len(files),
                "path": str(scan_path),
                "force": force,
                "message": f"Reindex job created with {len(files)} files.",
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_document_history(self, document_id: str, limit: int = 10) -> Dict[str, Any]:
        """Get version history for a document."""
        from src.utils.versioning import VersionManager

        vm = VersionManager()
        history = vm.get_history(document_id, limit=limit)
        total = len(vm.get_versions(document_id))
        return {"document_id": document_id, "versions": history, "total": total}

    async def get_document_diff(
        self, document_id: str, from_version: int, to_version: int
    ) -> Dict[str, Any]:
        """Get diff between two versions of a document."""
        from src.utils.versioning import VersionManager

        vm = VersionManager()
        diff = vm.get_diff(document_id, from_version, to_version)
        if not diff:
            return {"error": "Version(s) not found"}
        return {
            "from_version": from_version,
            "to_version": to_version,
            "additions": diff.additions,
            "deletions": diff.deletions,
            "summary": diff.summary,
            "diff_lines": diff.diff_lines[:50],
        }

    async def restore_document_version(
        self, document_id: str, version_number: int
    ) -> Dict[str, Any]:
        """Restore a previous version of a document."""
        from src.utils.versioning import VersionManager

        vm = VersionManager()
        restored = vm.restore_version(document_id, version_number)
        if not restored:
            return {"error": f"Version {version_number} not found"}
        return {
            "success": True,
            "new_version": restored.version_number,
            "restored_from": version_number,
        }

    async def list_vaults(self) -> Dict[str, Any]:
        """List configured Obsidian vaults."""
        from src.config import VAULT_PATHS

        return {
            "vaults": {
                name: {"path": str(path), "exists": path.exists()}
                for name, path in VAULT_PATHS.items()
            }
        }

    async def list_integrations(self) -> Dict[str, Any]:
        """List available integration plugins and their status."""
        integrations = []
        try:
            from src.integrations.readwise import ReadwisePlugin

            rw = ReadwisePlugin()
            integrations.append(
                {
                    "name": rw.name(),
                    "connected": rw.check_connection(),
                    "config": rw.get_config_schema(),
                }
            )
        except Exception as e:
            logger.debug(f"Readwise plugin unavailable: {e}")
        return {"integrations": integrations}

    async def sync_integration(self, name: str) -> Dict[str, Any]:
        """Run a sync cycle for a named integration."""
        if name == "readwise":
            from src.integrations.readwise import ReadwisePlugin

            plugin = ReadwisePlugin()
            if not plugin.check_connection():
                return {
                    "status": "error",
                    "error": "Readwise not connected (check READWISE_API_TOKEN)",
                }
            return plugin.sync()
        return {"status": "error", "error": f"Unknown integration: {name}"}
