"""
Episodic Memory / User Profile

Semantic Memory = knowledge from documents
Episodic Memory = knowledge about the USER

If the user says "I'm moving to Tokyo", that fact should persist
across sessions without being in a document.

This module:
1. Extracts user facts/preferences from conversations
2. Stores them in a structured profile
3. Injects them into system prompts for continuity
"""

import logging
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class FactCategory(str, Enum):
    """Categories of user facts."""
    PERSONAL = "personal"        # Name, location, etc.
    PREFERENCE = "preference"    # Likes, dislikes, styles
    LIFE_EVENT = "life_event"   # Moving, job change, etc.
    PROJECT = "project"         # Current projects, goals
    RELATIONSHIP = "relationship"  # People they mention
    TECHNICAL = "technical"     # Skills, tools, stack
    HEALTH = "health"           # If explicitly shared
    WORK = "work"               # Job, company, role


@dataclass
class UserFact:
    """A single fact about the user."""
    content: str
    category: FactCategory
    confidence: float
    source: str  # "conversation", "explicit", "inferred"
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None  # For temporary facts
    context: Optional[str] = None  # Where this was learned


@dataclass
class UserProfile:
    """Complete user profile with facts and preferences."""
    user_id: str
    name: Optional[str] = None
    facts: List[UserFact] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    context_window_priority: List[str] = field(default_factory=list)  # Categories to always include

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "facts": [asdict(f) for f in self.facts],
            "preferences": self.preferences,
            "context_window_priority": self.context_window_priority
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        facts = [
            UserFact(
                content=f["content"],
                category=FactCategory(f["category"]),
                confidence=f["confidence"],
                source=f["source"],
                created_at=f["created_at"],
                updated_at=f["updated_at"],
                expires_at=f.get("expires_at"),
                context=f.get("context")
            )
            for f in data.get("facts", [])
        ]
        return cls(
            user_id=data["user_id"],
            name=data.get("name"),
            facts=facts,
            preferences=data.get("preferences", {}),
            context_window_priority=data.get("context_window_priority", [])
        )


class FactExtractor:
    """
    Extracts facts about the user from conversations.

    Uses LLM to identify when user shares personal information.
    """

    EXTRACTION_PROMPT = """Analyze this conversation for facts about the user.

Conversation:
{conversation}

Extract any new facts about the user. Look for:
- Personal information (name, location, profession)
- Preferences (likes, dislikes, working style)
- Life events (moving, new job, projects)
- Technical details (skills, tools, setup)

Output JSON:
{{
  "facts": [
    {{"content": "...", "category": "personal|preference|life_event|project|technical|work", "confidence": 0.9}}
  ]
}}

Only include facts explicitly stated or strongly implied.
Output empty list if no new facts found.

JSON:"""

    def __init__(self, llm=None):
        self.llm = llm

    async def extract_facts(
        self,
        conversation: str,
        existing_facts: List[UserFact]
    ) -> List[UserFact]:
        """
        Extract new facts from a conversation.

        Args:
            conversation: Recent conversation text
            existing_facts: Already known facts (to avoid duplicates)

        Returns:
            List of new UserFacts
        """
        if not self.llm:
            return self._extract_with_patterns(conversation)

        try:
            prompt = self.EXTRACTION_PROMPT.format(
                conversation=conversation[-4000:]  # Limit context
            )

            response = await self.llm.generate(prompt, max_tokens=500)

            # Parse JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return []

            data = json.loads(json_match.group())

            now = datetime.now().isoformat()
            new_facts = []

            for f in data.get("facts", []):
                # Check if this is actually new
                if not self._is_duplicate(f["content"], existing_facts):
                    new_facts.append(UserFact(
                        content=f["content"],
                        category=FactCategory(f.get("category", "personal")),
                        confidence=f.get("confidence", 0.8),
                        source="conversation",
                        created_at=now,
                        updated_at=now
                    ))

            return new_facts

        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")
            return []

    def _extract_with_patterns(self, text: str) -> List[UserFact]:
        """Pattern-based extraction fallback."""
        import re

        facts = []
        now = datetime.now().isoformat()

        patterns = [
            (r"my name is (\w+)", FactCategory.PERSONAL),
            (r"I(?:'m| am) (?:a |an )?(\w+ developer|\w+ engineer|\w+ist)", FactCategory.WORK),
            (r"I(?:'m| am) moving to (\w+)", FactCategory.LIFE_EVENT),
            (r"I work (?:at|for) ([A-Z]\w+)", FactCategory.WORK),
            (r"I prefer (\w+)", FactCategory.PREFERENCE),
            (r"I use (\w+) for", FactCategory.TECHNICAL),
        ]

        for pattern, category in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                facts.append(UserFact(
                    content=match.group(0),
                    category=category,
                    confidence=0.7,
                    source="pattern",
                    created_at=now,
                    updated_at=now
                ))

        return facts

    def _is_duplicate(self, content: str, existing: List[UserFact]) -> bool:
        """Check if fact is a duplicate."""
        content_lower = content.lower()
        for fact in existing:
            if content_lower in fact.content.lower() or fact.content.lower() in content_lower:
                return True
        return False


class EpisodicMemoryManager:
    """
    Manages user profile persistence and injection.

    Usage:
        manager = EpisodicMemoryManager(profile_path)
        profile = manager.load_or_create("user123")
        manager.add_fact(profile, fact)
        system_prompt = manager.get_context_injection(profile)
    """

    def __init__(self, storage_path: Path):
        """
        Args:
            storage_path: Directory to store user profiles
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _profile_path(self, user_id: str) -> Path:
        return self.storage_path / f"{user_id}.json"

    def load_or_create(self, user_id: str, name: Optional[str] = None) -> UserProfile:
        """Load existing profile or create new one."""
        path = self._profile_path(user_id)

        if path.exists():
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                return UserProfile.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to load profile: {e}")

        # Create new profile
        profile = UserProfile(user_id=user_id, name=name)
        self.save(profile)
        return profile

    def save(self, profile: UserProfile):
        """Save profile to disk."""
        path = self._profile_path(profile.user_id)
        with open(path, "w") as f:
            json.dump(profile.to_dict(), f, indent=2)
        logger.debug(f"Saved profile: {profile.user_id}")

    def add_fact(self, profile: UserProfile, fact: UserFact):
        """Add a new fact to profile."""
        # Check for conflicts/updates
        for i, existing in enumerate(profile.facts):
            if existing.category == fact.category:
                # Update if newer info about same topic
                if self._should_update(existing, fact):
                    profile.facts[i] = fact
                    fact.updated_at = datetime.now().isoformat()
                    self.save(profile)
                    return

        # Add as new fact
        profile.facts.append(fact)
        self.save(profile)

    def _should_update(self, existing: UserFact, new: UserFact) -> bool:
        """Check if new fact should replace existing."""
        # Same category, higher confidence, or newer
        if new.confidence > existing.confidence:
            return True
        if new.content.lower() in existing.content.lower():
            return False  # Existing is more detailed
        return True

    def remove_expired_facts(self, profile: UserProfile):
        """Remove facts that have expired."""
        now = datetime.now()
        profile.facts = [
            f for f in profile.facts
            if not f.expires_at or datetime.fromisoformat(f.expires_at) > now
        ]
        self.save(profile)

    def get_context_injection(
        self,
        profile: UserProfile,
        max_facts: int = 10,
        categories: Optional[List[FactCategory]] = None
    ) -> str:
        """
        Generate context string for system prompt injection.

        Args:
            profile: User profile
            max_facts: Maximum facts to include
            categories: Filter by categories (None = all)

        Returns:
            Formatted string for system prompt
        """
        facts = profile.facts

        # Filter by category
        if categories:
            facts = [f for f in facts if f.category in categories]

        # Sort by confidence and recency
        facts = sorted(
            facts,
            key=lambda f: (f.confidence, f.updated_at),
            reverse=True
        )[:max_facts]

        if not facts:
            return ""

        # Format for injection
        lines = [
            "## About the User",
            ""
        ]

        if profile.name:
            lines.append(f"Name: {profile.name}")

        # Group by category
        by_category = {}
        for fact in facts:
            if fact.category not in by_category:
                by_category[fact.category] = []
            by_category[fact.category].append(fact.content)

        for category, contents in by_category.items():
            lines.append(f"\n### {category.value.title()}")
            for content in contents:
                lines.append(f"- {content}")

        return "\n".join(lines)

    def get_as_json(self, profile: UserProfile) -> str:
        """Get profile as JSON for structured injection."""
        return json.dumps({
            "user_name": profile.name,
            "facts": [
                {
                    "fact": f.content,
                    "category": f.category.value,
                    "confidence": f.confidence
                }
                for f in profile.facts[:20]
            ],
            "preferences": profile.preferences
        }, indent=2)


# Integration with conversation loop
class EpisodicMemoryMiddleware:
    """
    Middleware that extracts facts from conversations and injects profile.

    Usage in MCP server:
        middleware = EpisodicMemoryMiddleware(manager, extractor)

        # Before processing:
        system_prompt = base_prompt + middleware.get_injection(user_id)

        # After processing:
        await middleware.process_conversation(user_id, messages)
    """

    def __init__(
        self,
        manager: EpisodicMemoryManager,
        extractor: FactExtractor
    ):
        self.manager = manager
        self.extractor = extractor

    def get_injection(self, user_id: str) -> str:
        """Get context injection for system prompt."""
        profile = self.manager.load_or_create(user_id)
        return self.manager.get_context_injection(profile)

    async def process_conversation(
        self,
        user_id: str,
        messages: List[Dict[str, str]]
    ):
        """
        Process conversation to extract new facts.

        Args:
            user_id: User identifier
            messages: List of {"role": "user"|"assistant", "content": "..."}
        """
        profile = self.manager.load_or_create(user_id)

        # Only process user messages
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        conversation = "\n".join(user_messages[-5:])  # Last 5 messages

        new_facts = await self.extractor.extract_facts(
            conversation,
            profile.facts
        )

        for fact in new_facts:
            self.manager.add_fact(profile, fact)
            logger.info(f"Learned new fact about {user_id}: {fact.content[:50]}...")


# ── Session Tracking ─────────────────────────────────────────────────────────


@dataclass
class SessionEvent:
    """A single event in a session."""
    timestamp: str
    event_type: str  # "tool_call", "search", "chat", "ingestion"
    tool_name: str
    query: str = ""
    result_count: int = 0
    duration_ms: float = 0


@dataclass
class Session:
    """A user session with event history."""
    session_id: str
    started_at: str
    events: List[SessionEvent] = field(default_factory=list)
    ended_at: Optional[str] = None


class SessionTracker:
    """
    Lightweight session tracking for MCP tool usage.

    Logs tool calls, search queries, and chat interactions to disk
    for later analysis (popular queries, usage patterns, etc.).
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or Path.home() / ".corerag" / "sessions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._current: Optional[Session] = None
        self._start_session()

    def _start_session(self):
        """Start a new session."""
        import uuid
        self._current = Session(
            session_id=str(uuid.uuid4())[:8],
            started_at=datetime.now().isoformat(),
        )

    def log_event(
        self,
        event_type: str,
        tool_name: str,
        query: str = "",
        result_count: int = 0,
        duration_ms: float = 0,
    ):
        """Log a tool call or interaction event."""
        if not self._current:
            self._start_session()

        event = SessionEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            tool_name=tool_name,
            query=query,
            result_count=result_count,
            duration_ms=duration_ms,
        )
        self._current.events.append(event)

        # Auto-save every 10 events
        if len(self._current.events) % 10 == 0:
            self._save_current()

    def get_current_session(self) -> Optional[Dict]:
        """Get current session info."""
        if not self._current:
            return None
        return {
            "session_id": self._current.session_id,
            "started_at": self._current.started_at,
            "event_count": len(self._current.events),
            "events": [asdict(e) for e in self._current.events[-20:]],
        }

    def get_recent_sessions(self, limit: int = 10) -> List[Dict]:
        """Get recent session summaries from disk."""
        sessions = []
        for path in sorted(self.storage_dir.glob("session_*.json"), reverse=True)[:limit]:
            try:
                with open(path) as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", ""),
                    "started_at": data.get("started_at", ""),
                    "event_count": len(data.get("events", [])),
                })
            except Exception:
                continue
        return sessions

    def get_popular_queries(self, limit: int = 10) -> List[Dict]:
        """Aggregate most common search queries across sessions."""
        from collections import Counter
        queries = Counter()

        # Current session
        if self._current:
            for e in self._current.events:
                if e.query:
                    queries[e.query] += 1

        # Saved sessions (last 20)
        for path in sorted(self.storage_dir.glob("session_*.json"), reverse=True)[:20]:
            try:
                with open(path) as f:
                    data = json.load(f)
                for e in data.get("events", []):
                    if e.get("query"):
                        queries[e["query"]] += 1
            except Exception:
                continue

        return [{"query": q, "count": c} for q, c in queries.most_common(limit)]

    def end_session(self):
        """End and save current session."""
        if self._current:
            self._current.ended_at = datetime.now().isoformat()
            self._save_current()
            self._current = None

    def _save_current(self):
        """Save current session to disk."""
        if not self._current:
            return
        path = self.storage_dir / f"session_{self._current.session_id}.json"
        try:
            data = {
                "session_id": self._current.session_id,
                "started_at": self._current.started_at,
                "ended_at": self._current.ended_at,
                "events": [asdict(e) for e in self._current.events],
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save session: {e}")
