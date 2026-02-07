"""Personal context model for CoreRag."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class PersonalContext:
    """User's personal context for AI interactions."""

    # Identity
    name: str = ""
    email: Optional[str] = None
    role: Optional[str] = None
    location: Optional[str] = None

    # Preferences
    communication_style: str = "balanced"  # concise, balanced, detailed
    technical_level: str = "intermediate"  # beginner, intermediate, expert
    preferred_format: str = "markdown"  # markdown, plain, structured

    # Active projects
    current_projects: List[str] = field(default_factory=list)
    active_interests: List[str] = field(default_factory=list)

    # Goals
    short_term_goals: List[str] = field(default_factory=list)
    long_term_goals: List[str] = field(default_factory=list)

    # Environment
    hardware: Optional[str] = None
    tools: List[str] = field(default_factory=list)

    # Learning
    learning_topics: List[str] = field(default_factory=list)
    expertise_areas: List[str] = field(default_factory=list)

    # Insights (AI-discovered patterns)
    discovered_preferences: List[str] = field(default_factory=list)
    interaction_patterns: List[str] = field(default_factory=list)

    # Metadata
    updated_at: datetime = field(default_factory=datetime.now)
    version: int = 1

    @classmethod
    def load(cls, path: Path) -> "PersonalContext":
        """Load context from YAML file."""
        if not path.exists():
            return cls()

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Handle datetime
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])

        return cls(**data)

    def save(self, path: Path) -> None:
        """Save context to YAML file."""
        self.updated_at = datetime.now()
        self.version += 1

        data = self.to_dict()
        data["updated_at"] = data["updated_at"].isoformat()

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "location": self.location,
            "communication_style": self.communication_style,
            "technical_level": self.technical_level,
            "preferred_format": self.preferred_format,
            "current_projects": self.current_projects,
            "active_interests": self.active_interests,
            "short_term_goals": self.short_term_goals,
            "long_term_goals": self.long_term_goals,
            "hardware": self.hardware,
            "tools": self.tools,
            "learning_topics": self.learning_topics,
            "expertise_areas": self.expertise_areas,
            "discovered_preferences": self.discovered_preferences,
            "interaction_patterns": self.interaction_patterns,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    def format_for_claude(self) -> str:
        """Format context for Claude system prompt injection."""
        sections = []

        if self.name:
            identity = f"User: {self.name}"
            if self.role:
                identity += f" ({self.role})"
            sections.append(identity)

        if self.current_projects:
            sections.append(f"Current projects: {', '.join(self.current_projects)}")

        if self.active_interests:
            sections.append(f"Interests: {', '.join(self.active_interests)}")

        if self.learning_topics:
            sections.append(f"Currently learning: {', '.join(self.learning_topics)}")

        if self.communication_style != "balanced":
            sections.append(f"Prefers {self.communication_style} responses")

        if self.technical_level != "intermediate":
            sections.append(f"Technical level: {self.technical_level}")

        if self.hardware:
            sections.append(f"Hardware: {self.hardware}")

        return "\n".join(sections) if sections else "No personal context available."

    def update_from_interaction(self, insight: str, category: str = "preference") -> None:
        """Add an insight discovered from interactions."""
        self.discovered_preferences.append(f"[{datetime.now().isoformat()}] {insight}")
        self.updated_at = datetime.now()
