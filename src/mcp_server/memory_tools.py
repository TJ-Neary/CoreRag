"""Memory tool group — episodic memory and user context."""

import logging
from typing import Any, Dict

from src.config import STATE_DIR

logger = logging.getLogger(__name__)


class MemoryTools:
    """Episodic memory tools for user context and fact management."""

    def __init__(self):
        self._memory_manager = None
        self._user_profile = None

    def _ensure_memory(self):
        """Lazily initialize memory manager and load user profile."""
        if self._memory_manager is None:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            self._memory_manager = EpisodicMemoryManager(storage_path)
            self._user_profile = self._memory_manager.load_or_create("default")

    async def get_user_context(self) -> Dict[str, Any]:
        """Get user profile and episodic memory context."""
        self._ensure_memory()

        if not self._user_profile:
            return {"error": "User profile not initialized"}
        profile = self._user_profile

        # Get correction patterns from correction log
        correction_summary: Dict[str, Any] = {}
        try:
            from src.correction_log import _load_corrections

            corrections = _load_corrections()
            if corrections:
                folder_changes = []
                filename_changes = []
                for c in corrections[-20:]:
                    corr = c.get("corrections", {})
                    if "target_folder" in corr:
                        folder_changes.append(
                            f"{corr['target_folder']['ai']} -> {corr['target_folder']['human']}"
                        )
                    if "filename" in corr:
                        filename_changes.append(
                            f"{corr['filename']['ai']} -> {corr['filename']['human']}"
                        )
                if folder_changes:
                    correction_summary["folder_patterns"] = folder_changes[-5:]
                if filename_changes:
                    correction_summary["filename_patterns"] = filename_changes[-5:]
                correction_summary["total_corrections"] = len(corrections)
        except Exception as e:
            logger.warning(f"Failed to load correction patterns: {e}")

        return {
            "facts": [
                {"fact": f.content, "category": f.category.value, "confidence": f.confidence}
                for f in profile.facts
            ],
            "preferences": profile.preferences,
            "correction_patterns": correction_summary,
            "user_name": profile.name,
        }

    async def add_user_fact(
        self,
        fact: str,
        category: str = "general",
    ) -> Dict[str, Any]:
        """Add a fact about the user to episodic memory."""
        self._ensure_memory()

        from datetime import datetime

        from src.memory.episodic_memory import FactCategory, UserFact

        category_map = {
            "general": FactCategory.PERSONAL,
            "personal": FactCategory.PERSONAL,
            "preference": FactCategory.PREFERENCE,
            "life_event": FactCategory.LIFE_EVENT,
            "project": FactCategory.PROJECT,
            "relationship": FactCategory.RELATIONSHIP,
            "technical": FactCategory.TECHNICAL,
            "health": FactCategory.HEALTH,
            "work": FactCategory.WORK,
        }
        fact_category = category_map.get(category.lower(), FactCategory.PERSONAL)

        now = datetime.now().isoformat()
        user_fact = UserFact(
            content=fact,
            category=fact_category,
            confidence=1.0,
            source="explicit",
            created_at=now,
            updated_at=now,
        )

        if not self._memory_manager or not self._user_profile:
            return {"error": "Memory not initialized"}
        self._memory_manager.add_fact(self._user_profile, user_fact)
        logger.info(f"Stored user fact: [{fact_category.value}] {fact}")

        return {
            "stored": True,
            "fact": fact,
            "category": fact_category.value,
            "total_facts": len(self._user_profile.facts),
        }
