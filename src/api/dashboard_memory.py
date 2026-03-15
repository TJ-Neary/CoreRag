"""Dashboard episodic memory routes — user facts and correction patterns."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request

from src.config import STATE_DIR

logger = logging.getLogger(__name__)


def create_memory_router() -> APIRouter:
    """Create a router for episodic memory endpoints."""
    router = APIRouter()

    @router.get("/api/user-facts")
    async def get_user_facts() -> dict:
        """Get user facts and correction patterns for dashboard display."""
        try:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")

            facts = [
                {
                    "content": f.content,
                    "category": f.category.value,
                    "confidence": f.confidence,
                    "source": f.source,
                    "created_at": f.created_at,
                }
                for f in profile.facts
            ]

            corrections = []
            try:
                from src.correction_log import _load_corrections

                raw = _load_corrections()
                for c in raw[-20:]:
                    corrections.append(
                        {
                            "file": c.get("original_filename", ""),
                            "corrections": c.get("corrections", {}),
                            "timestamp": c.get("timestamp", ""),
                        }
                    )
            except Exception:
                pass

            return {
                "user_name": profile.name,
                "facts": facts,
                "corrections": corrections,
                "total_facts": len(facts),
                "total_corrections": len(corrections),
            }
        except Exception as e:
            return {"error": str(e), "facts": [], "corrections": []}

    @router.delete("/api/user-facts/{index}")
    async def delete_user_fact(index: int) -> dict:
        """Delete a user fact by index."""
        try:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")

            if 0 <= index < len(profile.facts):
                removed = profile.facts.pop(index)
                manager.save(profile)
                return {"success": True, "removed": removed.content}
            return {"success": False, "error": "Index out of range"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.post("/api/user-facts")
    async def add_user_fact(request: Request) -> dict:
        """Add a new user fact."""
        try:
            from src.memory.episodic_memory import (
                EpisodicMemoryManager,
                FactCategory,
                UserFact,
            )

            body = await request.json()
            content = body.get("content", "").strip()
            category = body.get("category", "personal")
            source = body.get("source", "explicit")

            if not content:
                return {"success": False, "error": "Content is required"}

            try:
                cat = FactCategory(category)
            except ValueError:
                valid = [c.value for c in FactCategory]
                return {"success": False, "error": f"Invalid category. Valid: {valid}"}

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")

            now = datetime.now().isoformat()
            fact = UserFact(
                content=content,
                category=cat,
                confidence=1.0,
                source=source,
                created_at=now,
                updated_at=now,
            )
            manager.add_fact(profile, fact)

            return {"success": True, "content": content, "category": category}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.get("/api/user-facts/stats")
    async def get_user_facts_stats() -> dict:
        """Get category breakdown and summary stats for user facts."""
        try:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")

            categories: dict[str, int] = {}
            sources: dict[str, int] = {}
            for f in profile.facts:
                cat = f.category.value
                categories[cat] = categories.get(cat, 0) + 1
                sources[f.source] = sources.get(f.source, 0) + 1

            return {
                "total_facts": len(profile.facts),
                "categories": categories,
                "sources": sources,
                "user_name": profile.name,
            }
        except Exception as e:
            return {"error": str(e), "total_facts": 0, "categories": {}, "sources": {}}

    @router.get("/api/user-facts/export")
    async def export_user_profile() -> dict:
        """Export user profile as JSON."""
        try:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")
            return profile.to_dict()
        except Exception as e:
            return {"error": str(e)}

    return router
