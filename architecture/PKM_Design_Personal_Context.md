# Personal Context Layer Design
## "About Me" System for Personalized AI Interactions

> **Status**: ✅ Core Complete | All major components implemented

*Last Updated: January 31, 2026*

---

## Purpose

The Personal Context Layer provides Claude (and future local LLMs) with persistent knowledge about you—your background, preferences, projects, and style—enabling deeply personalized interactions without repeating context every conversation.

Think of it as: **Claude's memory of who you are and how you work.**

---

## Design Philosophy

1. **Structured yet flexible** - Core categories with room for organic growth
2. **Queryable** - Claude can ask for specific context when relevant
3. **Updatable** - Learns and updates from conversations
4. **Privacy-first** - This is the most sensitive data; local-only by default
5. **Actionable** - Not just facts, but preferences that change behavior

---

## Context Categories

### 1. Identity & Background

Basic information for personalization and appropriate communication.

```yaml
identity:
  name: "TJ"
  preferred_name: "TJ"  # What Claude should call you
  pronouns: "he/him"    # Optional
  timezone: "America/New_York"
  locale: "en-US"

background:
  professional:
    current_role: "..."
    industry: "..."
    years_experience: ...
    expertise_areas:
      - "..."
      - "..."
    working_on: "Developing personal knowledge management systems"

  education:
    - degree: "..."
      field: "..."
      institution: "..."

  skills:
    strong:
      - "..."
    learning:
      - "Python"  # Starting course Feb 3, 2026
    interested_in:
      - "AI/ML"
      - "RAG systems"
      - "Local LLMs"
```

---

### 2. Preferences & Style

How you like to work and communicate.

```yaml
communication:
  formality: "casual"           # casual, professional, academic
  verbosity: "balanced"         # concise, balanced, detailed
  explanation_style: "examples" # examples, analogies, technical, step-by-step
  response_length: "adaptive"   # short, medium, long, adaptive

  likes:
    - "Concrete examples over abstract explanations"
    - "Being told what I might be missing or not thinking about"
    - "Practical, actionable suggestions"
    - "Direct answers before elaboration"

  dislikes:
    - "Excessive caveats and hedging"
    - "Being asked too many clarifying questions before starting"
    - "Overly formal language"

writing_style:
  tone: "conversational but informed"
  typical_formats:
    - "Newsletters"
    - "YouTube scripts"
    - "Technical documentation"
  samples:
    - document_id: "uuid-of-writing-sample-1"
    - document_id: "uuid-of-writing-sample-2"

  voice_characteristics:
    - "Uses analogies to explain complex topics"
    - "Tends toward longer, exploratory sentences"
    - "Balances enthusiasm with practicality"
```

---

### 3. Active Projects

What you're currently working on, enabling contextual awareness.

```yaml
projects:
  - id: "pkm-system"
    name: "Personal Knowledge Management System"
    status: "active"
    started: "2026-01-31"
    description: "Building a RAG-based knowledge system with MCP integration for Claude and future local LLMs"
    goals:
      - "Query personal research collection via Claude"
      - "Obsidian integration for visual exploration"
      - "Scale to terabyte collection"
      - "Future: Local LLM 'employee' concept"
    current_phase: "Design & Planning"
    key_decisions:
      - "LanceDB for vector storage"
      - "Single database with metadata collections"
      - "Python-based ingestion pipeline"
    blockers: []
    related_topics:
      - "AI/RAG"
      - "Technology/Programming/Python"
    context_documents:
      - "PKM_Project_Memory.docx"
      - "PKM_Design_Metadata_Schema.md"

  - id: "python-learning"
    name: "Python Course"
    status: "upcoming"
    starts: "2026-02-03"
    description: "4-week, 40-hour Intro to Python course"
    goals:
      - "Build foundational Python skills"
      - "Apply to PKM system development"
```

---

### 4. Interests & Research Areas

What topics you're interested in for content discovery and recommendations.

```yaml
interests:
  primary:
    - topic: "Artificial Intelligence"
      subtopics:
        - "Large Language Models"
        - "RAG systems"
        - "AI agents and computer use"
        - "Local/edge AI deployment"
      engagement: "deep"  # casual, moderate, deep

    - topic: "Personal Knowledge Management"
      subtopics:
        - "Obsidian and networked thought"
        - "Information organization"
        - "AI-augmented research"
      engagement: "deep"

  secondary:
    - topic: "..."
      engagement: "moderate"

  tracking:
    - "OpenManus / Manus bot developments"
    - "Apple Silicon ML capabilities"
    - "Local LLM advancements"

research_preferences:
  source_types_preferred:
    - "Research papers"
    - "Technical documentation"
    - "In-depth tutorials"
  source_types_avoided:
    - "Clickbait articles"
    - "Superficial overviews"
```

---

### 5. Goals & Aspirations

Longer-term objectives for strategic suggestions.

```yaml
goals:
  short_term:  # Next 1-3 months
    - "Get PKM system operational with 40 PDFs"
    - "Complete Python course"
    - "Build working MCP server"

  medium_term:  # 3-12 months
    - "Scale PKM to full document collection"
    - "Implement Obsidian integration with AI tagging"
    - "Explore local LLM deployment"

  long_term:  # 1+ years
    - "Develop 'AI employee' concept for local deployment"
    - "Potential business model: curated knowledge bases"

  learning_goals:
    - "Python proficiency"
    - "MCP server development"
    - "Vector database optimization"
```

---

### 6. Tools & Environment

Technical context for relevant suggestions.

```yaml
environment:
  hardware:
    primary: "2024 MacBook Pro M4 Max, 48GB RAM"
    capabilities:
      - "Can run 70B parameter models"
      - "Fast Whisper transcription"
      - "Efficient local embedding"

  software:
    os: "macOS"
    editors:
      - "VS Code"
      - "Cursor"
      - "Google AI IDE tools"
    key_tools:
      - "Obsidian"
      - "Claude Desktop"
      - "Terminal/zsh"

  preferences:
    package_manager: "homebrew"
    python_environment: "Learning; will use virtual environments"
    ai_coding_assistants: true
```

---

### 7. Conversation History Insights

Patterns learned from previous conversations (auto-populated).

```yaml
conversation_insights:
  topics_discussed:
    - topic: "PKM System Design"
      first_discussed: "2026-01-31"
      depth: "extensive"

  decisions_made:
    - date: "2026-01-31"
      decision: "Use single database with metadata collections"
      context: "PKM system architecture"

    - date: "2026-01-31"
      decision: "Obsidian for visual exploration, not note-taking"
      context: "PKM system design"

  preferences_learned:
    - "Likes comprehensive planning before implementation"
    - "Prefers brainstorming with feedback on what might be missing"
    - "Interested in future-proofing and scalability"

  clarifications_made:
    - "Obsidian will be separate from personal note-taking vault"
    - "Privacy hybrid approach: local preferred, API for processing acceptable"
```

---

## Storage Format

Context stored as structured YAML documents in the `context` collection:

```
context/
├── identity.yaml
├── preferences.yaml
├── projects/
│   ├── pkm-system.yaml
│   └── python-learning.yaml
├── interests.yaml
├── goals.yaml
├── environment.yaml
└── insights/
    └── conversation_insights.yaml
```

Each file is also embedded as vectors for semantic retrieval ("what are my goals related to AI?").

---

## Retrieval Patterns

### Query by Category
```python
# Get all communication preferences
context = await get_context(context_type="preferences.communication")
```

### Query by Relevance
```python
# Find context relevant to current topic
context = await search_knowledge(
    query="Python learning goals",
    collections=["context"]
)
```

### Composite Context
```python
# Build context packet for content creation
async def get_writing_context():
    return {
        "style": await get_context("preferences.writing_style"),
        "voice": await get_context("preferences.voice_characteristics"),
        "samples": await get_related_documents("writing_samples"),
    }
```

---

## Update Mechanisms

### Explicit Updates
User can tell Claude to update context:
> "Remember that I prefer bullet points for technical documentation."

Claude calls:
```python
await update_context(
    path="preferences.writing_style.format_preferences",
    value="bullet points for technical documentation",
    source="user_instruction"
)
```

### Implicit Learning
After conversations, extract insights:
```python
async def extract_conversation_insights(conversation):
    """Analyze conversation for implicit preferences and decisions."""
    # Use LLM to identify:
    # - Preferences expressed
    # - Decisions made
    # - New project information
    # - Style patterns
    return insights

async def update_from_conversation(insights):
    """Merge learned insights into context."""
    # Add to conversation_insights
    # Update relevant preference sections
    # Flag for user confirmation if uncertain
```

### Review Queue
Uncertain updates go to a review queue:
```yaml
pending_updates:
  - suggested: "Add 'dislikes lengthy preambles' to communication.dislikes"
    source: "Inferred from conversation 2026-01-31"
    confidence: 0.7
    status: "pending_review"
```

---

## Privacy Considerations

The context layer is **highly sensitive**:

1. **Local-only storage** - Never sent to cloud APIs unless explicitly requested
2. **Encrypted at rest** - Optional encryption for context files
3. **Selective sharing** - User can mark specific context as shareable
4. **Audit log** - Track when and how context is accessed

```yaml
privacy:
  sharing_allowed:
    - "preferences.communication"   # OK to share with cloud
    - "interests.primary"           # OK to share
  sharing_blocked:
    - "identity"                    # Never share
    - "projects"                    # Contains proprietary info
    - "environment"                 # System details
```

---

## Example: Claude Using Context

**User**: "Write me a newsletter about recent developments in local LLMs"

**Claude's internal process**:
1. Get writing context → casual tone, conversational style
2. Get interests → knows user tracks local LLM advancements
3. Get projects → knows PKM project relates to this
4. Get research collection → find user's saved documents on topic
5. Get preferences → knows user likes practical, actionable content

**Result**: Newsletter written in user's voice, referencing their own research, tied to their PKM project goals.

---

## Initial Context Bootstrap

For new users, create starter context through onboarding:

```python
async def onboard_user():
    """Interactive context collection."""
    questions = [
        ("What should I call you?", "identity.preferred_name"),
        ("What's your primary work/interest area?", "background.working_on"),
        ("Do you prefer concise or detailed explanations?", "preferences.verbosity"),
        ("Any current projects I should know about?", "projects"),
    ]

    for question, path in questions:
        response = await ask_user(question)
        await set_context(path, response)
```

---

## Integration Points

### With MCP Server
- `get_context()` tool for retrieval
- `update_context()` tool for modifications
- Automatic context injection for relevant queries

### With Obsidian
- Context files synced to dedicated vault folder
- Visual graph of interests and project connections
- Quick reference for the human

### With Ingestion Pipeline
- New documents auto-tagged based on interest areas
- Relevance scoring based on project goals
- Priority queue based on tracking list

---

## Future Enhancements

1. **Multi-model context** - Different summaries for different LLMs
2. **Temporal context** - "What was I working on last month?"
3. **Collaborative context** - Shared team knowledge (for business use)
4. **Context compression** - Efficient representation for limited context windows
5. **Mood/energy awareness** - Adapt responses to user state (if shared)
