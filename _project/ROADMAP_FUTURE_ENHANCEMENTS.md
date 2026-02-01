# AntiGravity PKM: Future Enhancements Roadmap

> **Created**: 2026-02-01  
> **Status**: Planning  
> **Scope**: Post-Phase 6 improvements identified during codebase review

---

## Executive Summary

This document captures enhancement opportunities identified during a comprehensive review of the AntiGravity PKM v2.0 codebase. These suggestions build on the existing architecture and leverage code that's already written but not fully wired up.

### Priority Tiers

| Tier | Focus | Timeline |
|------|-------|----------|
| **P0** | High impact, code exists | Weeks 1-2 |
| **P1** | Significant value, moderate effort | Weeks 3-6 |
| **P2** | Quality of life improvements | Weeks 7-10 |
| **P3** | Future considerations | Backlog |

---

## P0: High Priority — Wire Up Existing Code

### 1. Knowledge Graph MCP Integration

**Current State**: `src/graph/knowledge_graph.py` has a complete implementation with entity extraction, relationship storage, path-finding, and graph-enhanced retrieval. However, `search_by_entity` in MCP tools is a stub that falls back to semantic search.

**Impact**: Enables Claude to answer relationship questions like "What concepts are related to Total Rewards?" by traversing actual entity relationships, not just vector similarity.

**Implementation**:

```python
# In src/mcp_server/tools.py

from src.graph.knowledge_graph import KnowledgeGraph, EntityExtractor

class PKMTools:
    def __init__(self, ..., graph_db_path: Optional[Path] = None):
        # ... existing init ...
        self.knowledge_graph = KnowledgeGraph(
            graph_db_path or Path.home() / ".pkm" / "knowledge_graph.db"
        )
    
    async def search_by_entity(
        self,
        entity_name: str,
        relationship_type: Optional[str] = None,
        max_hops: int = 2,
    ) -> Dict[str, Any]:
        """Search using the knowledge graph for entity relationships."""
        
        # Get direct neighbors
        neighbors = self.knowledge_graph.get_neighbors(
            entity_name,
            relationship_types=[relationship_type] if relationship_type else None,
            direction="both"
        )
        
        # Get graph stats for context
        stats = self.knowledge_graph.get_stats()
        
        # If entity not found, fall back to semantic search
        if not neighbors:
            semantic_results = await self.search_knowledge(
                query=entity_name, k=5, use_reranker=True
            )
            return {
                "entity": entity_name,
                "graph_available": True,
                "entity_found": False,
                "fallback": "semantic_search",
                "results": semantic_results.get("results", []),
                "suggestion": f"Entity '{entity_name}' not in graph. Consider re-indexing with entity extraction enabled."
            }
        
        # Group by relationship type
        by_relationship = {}
        for n in neighbors:
            rel = n["relationship"]
            if rel not in by_relationship:
                by_relationship[rel] = []
            by_relationship[rel].append({
                "entity": n["entity"],
                "direction": n["direction"],
                "document_id": n["document_id"],
                "confidence": n["confidence"]
            })
        
        return {
            "entity": entity_name,
            "graph_available": True,
            "entity_found": True,
            "relationships": by_relationship,
            "total_connections": len(neighbors),
            "graph_stats": {
                "total_entities": stats["total_entities"],
                "total_relationships": stats["total_relationships"]
            }
        }
```

**Entity Extraction During Ingestion**:

```python
# In src/executor.py, add to _index_in_rag()

from src.graph.knowledge_graph import KnowledgeGraph, EntityExtractor

async def _extract_and_store_entities(text: str, document_id: str, file_name: str):
    """Extract entities and relationships, store in knowledge graph."""
    try:
        graph = KnowledgeGraph(Path.home() / ".pkm" / "knowledge_graph.db")
        extractor = EntityExtractor()  # Uses regex fallback if no LLM
        
        entities, relationships = await extractor.extract(text[:10000], document_id)
        
        if entities or relationships:
            graph.add_from_extraction(entities, relationships)
            logger.info(
                f"Extracted {len(entities)} entities, {len(relationships)} relationships "
                f"from {file_name}"
            )
    except Exception as e:
        logger.warning(f"Entity extraction failed for {file_name}: {e}")
```

**Files to modify**:
- `src/mcp_server/tools.py` — Wire up `search_by_entity`
- `src/mcp_server/server.py` — Register new tool
- `src/executor.py` — Add entity extraction to ingestion pipeline

**Estimated effort**: 4-6 hours

---

### 2. Query Analytics → Episodic Memory Unification

**Current State**: `src/analytics/query_analytics.py` tracks searches separately from the planned episodic memory system. This creates two parallel observability systems.

**Impact**: Unified context for Claude that includes search behavior, knowledge gaps, and session history in one place.

**Implementation**:

```python
# In src/memory/episodic_memory.py (new consolidated module)

from src.analytics.query_analytics import QueryAnalytics, QueryEvent
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sqlite3
from pathlib import Path

@dataclass
class UnifiedContext:
    """Complete user context for MCP sessions."""
    # From episodic memory
    facts: List[str]
    preferences: Dict[str, any]
    recent_sessions: List[Dict]
    correction_patterns: Dict[str, str]
    
    # From query analytics
    frequent_searches: List[str]
    knowledge_gaps: List[Dict]  # Searches with poor results
    search_patterns: List[str]
    
    # Derived
    current_focus: str
    suggested_actions: List[str]


class UnifiedMemorySystem:
    """
    Consolidates episodic memory, corrections, and query analytics.
    
    Single source of truth for user context.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / ".pkm" / "memory.db"
        self.analytics = QueryAnalytics(state_dir=self.db_path.parent / "analytics")
        self._init_db()
    
    def _init_db(self):
        """Initialize unified memory schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # User facts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                source TEXT DEFAULT 'explicit',
                confidence REAL DEFAULT 1.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            )
        """)
        
        # Session summaries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id TEXT PRIMARY KEY,
                start_time TEXT NOT NULL,
                end_time TEXT,
                summary TEXT,
                topics TEXT,  -- JSON array
                tools_used TEXT,  -- JSON array
                documents_accessed TEXT,  -- JSON array
                searches_performed INTEGER DEFAULT 0
            )
        """)
        
        # Correction patterns table (aggregated from correction_log.json)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS correction_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,  -- 'folder', 'filename', 'sensitivity'
                from_value TEXT,
                to_value TEXT,
                frequency INTEGER DEFAULT 1,
                last_seen TEXT,
                UNIQUE(pattern_type, from_value, to_value)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get_unified_context(self) -> UnifiedContext:
        """Get complete user context for MCP session."""
        
        # Load facts
        facts = self._get_active_facts()
        
        # Load preferences (derived from facts + corrections)
        preferences = self._derive_preferences()
        
        # Load recent sessions
        recent_sessions = self._get_recent_sessions(days=7)
        
        # Load correction patterns
        correction_patterns = self._get_correction_patterns()
        
        # Get analytics data
        analytics_summary = self.analytics.get_summary(days=7)
        failed_queries = self.analytics.get_failed_queries(limit=5)
        
        # Build knowledge gaps
        knowledge_gaps = [
            {
                "query": q.query,
                "attempts": 1,  # Could aggregate
                "last_tried": q.timestamp,
                "best_score": q.top_result_score
            }
            for q in failed_queries
        ]
        
        # Derive current focus from recent activity
        current_focus = self._infer_current_focus(recent_sessions, analytics_summary)
        
        # Generate suggested actions
        suggested_actions = self._generate_suggestions(
            knowledge_gaps, correction_patterns, analytics_summary
        )
        
        return UnifiedContext(
            facts=facts,
            preferences=preferences,
            recent_sessions=recent_sessions,
            correction_patterns=correction_patterns,
            frequent_searches=analytics_summary.top_queries[:5],
            knowledge_gaps=knowledge_gaps,
            search_patterns=[p.pattern for p in self.analytics.get_patterns()[:5]],
            current_focus=current_focus,
            suggested_actions=suggested_actions
        )
    
    def _generate_suggestions(
        self,
        knowledge_gaps: List[Dict],
        correction_patterns: Dict,
        analytics: any
    ) -> List[str]:
        """Generate actionable suggestions based on patterns."""
        suggestions = []
        
        # Knowledge gap suggestions
        if knowledge_gaps:
            gap_topics = [g["query"] for g in knowledge_gaps[:3]]
            suggestions.append(
                f"Consider adding documents about: {', '.join(gap_topics)}"
            )
        
        # Correction pattern suggestions
        if correction_patterns.get("folder"):
            suggestions.append(
                "Your folder corrections suggest updating the LLM's category mappings"
            )
        
        # Quality suggestions
        if analytics.quality_trend == "declining":
            suggestions.append(
                "Search quality has declined recently. Consider re-indexing or adding to Golden Set."
            )
        
        return suggestions
    
    # ... additional helper methods ...
```

**MCP Tool Update**:

```python
# In src/mcp_server/tools.py

async def get_user_context(self) -> Dict[str, Any]:
    """Get user profile and episodic memory context."""
    from src.memory.episodic_memory import UnifiedMemorySystem
    
    memory = UnifiedMemorySystem()
    context = memory.get_unified_context()
    
    return {
        "facts": context.facts,
        "preferences": context.preferences,
        "recent_sessions": context.recent_sessions,
        "correction_patterns": context.correction_patterns,
        "frequent_searches": context.frequent_searches,
        "knowledge_gaps": context.knowledge_gaps,
        "current_focus": context.current_focus,
        "suggested_actions": context.suggested_actions
    }
```

**Files to modify**:
- `src/memory/episodic_memory.py` — Create unified system
- `src/mcp_server/tools.py` — Wire up `get_user_context`
- `src/analytics/query_analytics.py` — Add integration hooks

**Estimated effort**: 8-12 hours

---

### 3. Database Health MCP Tools

**Current State**: `src/maintenance/db_optimizer.py` has full optimization and health reporting, but no MCP exposure.

**Impact**: Claude can proactively suggest maintenance and users can trigger optimization without command line.

**Implementation**:

```python
# In src/mcp_server/tools.py

from src.maintenance.db_optimizer import LanceDBOptimizer, check_database_health

async def get_system_status(self) -> Dict[str, Any]:
    """Get current system status including memory, ingestion state, and health."""
    import psutil
    
    # Memory status
    memory = psutil.virtual_memory()
    
    # Database health
    try:
        health = check_database_health()
        db_status = {
            "total_size_mb": health.total_size_mb,
            "fragmentation": health.fragmentation_estimate,
            "tables": health.tables,
            "recommendations": health.recommendations
        }
    except Exception as e:
        db_status = {"error": str(e)}
    
    # Ingestion queue
    queue_status = await self.get_ingestion_queue()
    
    return {
        "memory": {
            "percent_used": memory.percent,
            "available_gb": memory.available / (1024**3),
            "total_gb": memory.total / (1024**3),
            "warning": memory.percent > 75
        },
        "database": db_status,
        "ingestion_queue": queue_status,
        "status": "warning" if memory.percent > 75 or health.fragmentation_estimate > 0.3 else "healthy"
    }

async def run_database_optimization(
    self,
    table_name: Optional[str] = None
) -> Dict[str, Any]:
    """Run database optimization to reduce fragmentation and improve performance."""
    from src.maintenance.db_optimizer import LanceDBOptimizer
    
    optimizer = LanceDBOptimizer()
    
    if table_name:
        result = optimizer.optimize_table(table_name)
        return {
            "table": result.table_name,
            "success": result.success,
            "space_saved_mb": result.space_saved_mb,
            "duration_seconds": result.duration_seconds,
            "error": result.error
        }
    else:
        results = optimizer.optimize_all()
        return {
            "tables_optimized": len(results),
            "total_space_saved_mb": sum(r.space_saved_mb for r in results),
            "all_successful": all(r.success for r in results),
            "details": [
                {
                    "table": r.table_name,
                    "success": r.success,
                    "space_saved_mb": r.space_saved_mb
                }
                for r in results
            ]
        }
```

**Register in FastMCP**:

```python
# In register_tools()

@mcp.tool()
async def get_system_status() -> dict:
    """Get system health including memory, database, and ingestion status."""
    return await tools.get_system_status()

@mcp.tool()
async def run_database_optimization(table_name: str = None) -> dict:
    """Optimize database to reduce fragmentation. Optionally specify a table."""
    return await tools.run_database_optimization(table_name)
```

**Files to modify**:
- `src/mcp_server/tools.py` — Add new methods
- `src/mcp_server/server.py` — Register tools

**Estimated effort**: 2-3 hours

---

## P1: Significant Value — Moderate Effort

### 4. Obsidian Export Enhancement: Auto-Backlinks

**Current State**: `src/obsidian/obsidian_export.py` creates standalone markdown files with frontmatter but no connections to existing vault content.

**Impact**: Transforms PKM imports from isolated files into connected knowledge nodes.

**Implementation**:

```python
# In src/obsidian/obsidian_export.py

import re
from pathlib import Path
from typing import List, Set, Dict, Optional
import sqlite3


class BacklinkGenerator:
    """Generate Obsidian wikilinks for imported content."""
    
    def __init__(self, vault_path: Path, graph_db_path: Optional[Path] = None):
        self.vault_path = vault_path
        self.graph_db_path = graph_db_path
        self._vault_files: Set[str] = set()
        self._refresh_vault_index()
    
    def _refresh_vault_index(self):
        """Index all markdown files in vault for linking."""
        self._vault_files = set()
        for md_file in self.vault_path.rglob("*.md"):
            # Store both filename and title (without extension)
            name = md_file.stem
            self._vault_files.add(name.lower())
    
    def find_linkable_terms(self, content: str) -> Dict[str, str]:
        """
        Find terms in content that match existing vault files.
        
        Returns:
            Dict mapping original term -> wikilink format
        """
        linkable = {}
        
        # Check each vault file name against content
        for vault_name in self._vault_files:
            # Case-insensitive search for the term
            pattern = re.compile(rf'\b({re.escape(vault_name)})\b', re.IGNORECASE)
            matches = pattern.findall(content)
            
            if matches:
                # Use the first match's actual case
                original = matches[0]
                # Create wikilink with proper case
                linkable[original] = f"[[{vault_name}|{original}]]"
        
        return linkable
    
    def get_entity_links(self, document_id: str) -> List[str]:
        """Get related entities from knowledge graph for 'Related' section."""
        if not self.graph_db_path or not self.graph_db_path.exists():
            return []
        
        try:
            conn = sqlite3.connect(self.graph_db_path)
            cursor = conn.cursor()
            
            # Get entities from this document
            cursor.execute(
                "SELECT DISTINCT name FROM entities WHERE document_id = ?",
                (document_id,)
            )
            entities = [row[0] for row in cursor.fetchall()]
            
            # Find which entities have vault files
            related = []
            for entity in entities:
                if entity.lower() in self._vault_files:
                    related.append(f"[[{entity}]]")
            
            conn.close()
            return related
            
        except Exception:
            return []
    
    def enhance_content(
        self,
        content: str,
        document_id: str,
        auto_link: bool = True,
        add_related_section: bool = True
    ) -> str:
        """
        Enhance content with backlinks.
        
        Args:
            content: Original markdown content
            document_id: Document ID for graph lookup
            auto_link: Replace matching terms with wikilinks
            add_related_section: Add "Related Documents" section
        
        Returns:
            Enhanced content with wikilinks
        """
        enhanced = content
        
        # Auto-link matching terms
        if auto_link:
            linkable = self.find_linkable_terms(content)
            for original, wikilink in linkable.items():
                # Only replace first occurrence to avoid over-linking
                enhanced = enhanced.replace(original, wikilink, 1)
        
        # Add related section
        if add_related_section:
            related = self.get_entity_links(document_id)
            if related:
                related_section = "\n\n---\n\n## Related\n\n"
                related_section += "\n".join(f"- {link}" for link in related)
                enhanced += related_section
        
        return enhanced


class ObsidianExporter:
    """Exports content to an Obsidian vault with backlink support."""
    
    def __init__(self, vault_path: Optional[Path] = None):
        # ... existing init ...
        self.backlink_generator = None
        if self.vault_path:
            self.backlink_generator = BacklinkGenerator(
                self.vault_path,
                Path.home() / ".pkm" / "knowledge_graph.db"
            )
    
    def export_to_vault(
        self,
        source_path: Path,
        content: str,
        metadata: Dict[str, Any],
        enable_backlinks: bool = True
    ) -> Optional[Path]:
        """Create markdown file in Obsidian vault with optional backlinks."""
        
        # ... existing validation ...
        
        # Generate document ID for graph lookup
        import hashlib
        document_id = hashlib.sha256(content[:5000].encode()).hexdigest()[:16]
        
        # Enhance content with backlinks
        if enable_backlinks and self.backlink_generator:
            content = self.backlink_generator.enhance_content(
                content,
                document_id,
                auto_link=True,
                add_related_section=True
            )
        
        # ... rest of existing export logic ...
```

**Configuration**:

```yaml
# In .env or config
PKM_OBSIDIAN_AUTO_BACKLINKS=true
PKM_OBSIDIAN_RELATED_SECTION=true
```

**Files to modify**:
- `src/obsidian/obsidian_export.py` — Add BacklinkGenerator class
- `src/executor.py` — Pass backlink options to exporter

**Estimated effort**: 6-8 hours

---

### 5. Dashboard Enhancements: Bulk Operations & Keyboard Navigation

**Current State**: Dashboard is functional but requires individual clicks for each item.

**Impact**: Dramatically faster review of large batches (like your 42 PHR docs).

**Implementation**:

```html
<!-- Add to dashboard.html -->

<script>
// Keyboard navigation and bulk operations
class DashboardEnhancements {
    constructor() {
        this.selectedItems = new Set();
        this.currentIndex = 0;
        this.items = [];
        this.recentFolders = this.loadRecentFolders();
        
        this.initKeyboardNav();
        this.initBulkSelect();
        this.initQuickAssign();
    }
    
    initKeyboardNav() {
        document.addEventListener('keydown', (e) => {
            // Ignore if typing in input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                return;
            }
            
            switch(e.key) {
                case 'j':
                case 'ArrowDown':
                    this.navigateNext();
                    break;
                case 'k':
                case 'ArrowUp':
                    this.navigatePrev();
                    break;
                case 'a':
                    this.approveCurrentItem();
                    break;
                case 's':
                    this.skipCurrentItem();
                    break;
                case 'e':
                    this.editCurrentItem();
                    break;
                case 'Space':
                    e.preventDefault();
                    this.toggleSelectCurrent();
                    break;
                case 'Enter':
                    if (e.shiftKey) {
                        this.bulkApprove();
                    }
                    break;
                case '1':
                case '2':
                case '3':
                case '4':
                case '5':
                    this.quickAssignFolder(parseInt(e.key) - 1);
                    break;
            }
        });
    }
    
    initBulkSelect() {
        // Shift+click for range selection
        document.querySelectorAll('.item-card').forEach((card, index) => {
            card.addEventListener('click', (e) => {
                if (e.shiftKey && this.lastClickedIndex !== null) {
                    // Select range
                    const start = Math.min(this.lastClickedIndex, index);
                    const end = Math.max(this.lastClickedIndex, index);
                    for (let i = start; i <= end; i++) {
                        this.selectedItems.add(this.items[i].id);
                    }
                    this.updateSelectionUI();
                } else if (e.ctrlKey || e.metaKey) {
                    // Toggle single selection
                    this.toggleSelect(this.items[index].id);
                }
                this.lastClickedIndex = index;
            });
        });
    }
    
    initQuickAssign() {
        // Show recent folders dropdown
        const quickAssignHTML = `
            <div class="quick-assign-panel" id="quickAssign">
                <h4>Quick Assign (1-5)</h4>
                <ul class="recent-folders">
                    ${this.recentFolders.map((folder, i) => 
                        `<li><kbd>${i+1}</kbd> ${folder}</li>`
                    ).join('')}
                </ul>
                <button onclick="dashboard.bulkApprove()" class="bulk-btn">
                    Approve Selected (Shift+Enter)
                </button>
            </div>
        `;
        document.querySelector('.sidebar').insertAdjacentHTML('beforeend', quickAssignHTML);
    }
    
    quickAssignFolder(index) {
        if (index >= this.recentFolders.length) return;
        
        const folder = this.recentFolders[index];
        
        if (this.selectedItems.size > 0) {
            // Bulk assign
            this.selectedItems.forEach(id => {
                this.assignFolder(id, folder);
            });
        } else {
            // Assign to current item
            this.assignFolder(this.items[this.currentIndex].id, folder);
        }
    }
    
    assignFolder(itemId, folder) {
        fetch(`/api/items/${itemId}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                proposed: { target_folder: folder }
            })
        }).then(() => this.refreshItem(itemId));
        
        this.trackRecentFolder(folder);
    }
    
    trackRecentFolder(folder) {
        this.recentFolders = [
            folder,
            ...this.recentFolders.filter(f => f !== folder)
        ].slice(0, 5);
        localStorage.setItem('recentFolders', JSON.stringify(this.recentFolders));
    }
    
    loadRecentFolders() {
        const saved = localStorage.getItem('recentFolders');
        return saved ? JSON.parse(saved) : [
            'Knowledge/Certifications/PHR',
            'Knowledge/Certifications/SPHR',
            'Career Search/Applications',
            'Work/USAA',
            'Personal/Military Records'
        ];
    }
    
    bulkApprove() {
        if (this.selectedItems.size === 0) {
            alert('No items selected. Use Space to select items.');
            return;
        }
        
        if (!confirm(`Approve ${this.selectedItems.size} items?`)) {
            return;
        }
        
        this.selectedItems.forEach(id => {
            fetch(`/api/items/${id}/approve`, { method: 'POST' });
        });
        
        this.selectedItems.clear();
        this.updateSelectionUI();
        this.refreshList();
    }
    
    applyToSimilar() {
        // When user corrects a category, offer to apply to similar items
        const currentItem = this.items[this.currentIndex];
        const originalCategory = currentItem.metadata.category;
        const newFolder = currentItem.proposed.target_folder;
        
        const similar = this.items.filter(item => 
            item.metadata.category === originalCategory &&
            item.proposed.target_folder !== newFolder &&
            item.status === 'pending'
        );
        
        if (similar.length > 0 && confirm(
            `Apply folder "${newFolder}" to ${similar.length} other "${originalCategory}" items?`
        )) {
            similar.forEach(item => {
                this.assignFolder(item.id, newFolder);
            });
        }
    }
    
    // ... navigation methods ...
}

// Initialize on page load
const dashboard = new DashboardEnhancements();
</script>

<style>
/* Selection styling */
.item-card.selected {
    border: 2px solid #3b82f6;
    background-color: #eff6ff;
}

.item-card.current {
    border-left: 4px solid #10b981;
}

.quick-assign-panel {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

.recent-folders li {
    padding: 4px 8px;
    cursor: pointer;
}

.recent-folders li:hover {
    background: #f3f4f6;
}

.recent-folders kbd {
    background: #e5e7eb;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: monospace;
    margin-right: 8px;
}

.bulk-btn {
    width: 100%;
    margin-top: 12px;
    padding: 8px 16px;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}

/* Keyboard shortcut hints */
.shortcut-hint {
    position: fixed;
    bottom: 20px;
    left: 20px;
    background: rgba(0,0,0,0.8);
    color: white;
    padding: 12px;
    border-radius: 8px;
    font-size: 12px;
}
</style>

<!-- Shortcut hints -->
<div class="shortcut-hint">
    <strong>Shortcuts:</strong><br>
    j/k or ↑/↓: Navigate | Space: Select<br>
    a: Approve | s: Skip | e: Edit<br>
    1-5: Quick folder | Shift+Enter: Bulk approve
</div>
```

**Files to modify**:
- `src/dashboard/templates/dashboard.html` — Add JS enhancements
- `src/dashboard/api.py` — Add bulk endpoints if needed

**Estimated effort**: 6-8 hours

---

### 6. PII Dictionary Management via MCP

**Current State**: PII redaction loads custom terms from `~/.pkm/pii_terms.yaml` but requires manual file editing.

**Impact**: Claude can help manage PII patterns during conversation.

**Implementation**:

```python
# In src/mcp_server/tools.py

import yaml
from pathlib import Path

PII_TERMS_PATH = Path.home() / ".pkm" / "pii_terms.yaml"

async def get_pii_terms(self) -> Dict[str, Any]:
    """Get current custom PII terms."""
    if not PII_TERMS_PATH.exists():
        return {"terms": [], "message": "No custom PII terms configured"}
    
    with open(PII_TERMS_PATH) as f:
        terms = yaml.safe_load(f) or {}
    
    return {
        "terms": terms.get("custom_terms", []),
        "patterns": terms.get("patterns", []),
        "total_count": len(terms.get("custom_terms", [])) + len(terms.get("patterns", []))
    }

async def add_pii_term(
    self,
    term: str,
    category: str = "custom",
    is_pattern: bool = False
) -> Dict[str, Any]:
    """
    Add a custom term to the PII redaction dictionary.
    
    Args:
        term: The term or regex pattern to redact
        category: Category for the term (e.g., 'account_number', 'custom')
        is_pattern: If True, treat as regex pattern
    
    Returns:
        Confirmation with updated term count
    """
    # Load existing terms
    if PII_TERMS_PATH.exists():
        with open(PII_TERMS_PATH) as f:
            terms = yaml.safe_load(f) or {}
    else:
        terms = {"custom_terms": [], "patterns": []}
    
    # Add to appropriate list
    entry = {"value": term, "category": category}
    
    if is_pattern:
        if "patterns" not in terms:
            terms["patterns"] = []
        if entry not in terms["patterns"]:
            terms["patterns"].append(entry)
    else:
        if "custom_terms" not in terms:
            terms["custom_terms"] = []
        if entry not in terms["custom_terms"]:
            terms["custom_terms"].append(entry)
    
    # Save
    PII_TERMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PII_TERMS_PATH, 'w') as f:
        yaml.dump(terms, f, default_flow_style=False)
    
    return {
        "added": True,
        "term": term,
        "category": category,
        "is_pattern": is_pattern,
        "total_terms": len(terms.get("custom_terms", [])),
        "total_patterns": len(terms.get("patterns", []))
    }

async def remove_pii_term(self, term: str) -> Dict[str, Any]:
    """Remove a custom PII term."""
    if not PII_TERMS_PATH.exists():
        return {"removed": False, "error": "No custom terms file exists"}
    
    with open(PII_TERMS_PATH) as f:
        terms = yaml.safe_load(f) or {}
    
    removed = False
    
    # Check custom_terms
    for i, entry in enumerate(terms.get("custom_terms", [])):
        if entry.get("value") == term:
            terms["custom_terms"].pop(i)
            removed = True
            break
    
    # Check patterns
    if not removed:
        for i, entry in enumerate(terms.get("patterns", [])):
            if entry.get("value") == term:
                terms["patterns"].pop(i)
                removed = True
                break
    
    if removed:
        with open(PII_TERMS_PATH, 'w') as f:
            yaml.dump(terms, f, default_flow_style=False)
    
    return {"removed": removed, "term": term}
```

**Register tools**:

```python
@mcp.tool()
async def get_pii_terms() -> dict:
    """Get current custom PII redaction terms."""
    return await tools.get_pii_terms()

@mcp.tool()
async def add_pii_term(term: str, category: str = "custom", is_pattern: bool = False) -> dict:
    """Add a custom term or pattern to PII redaction."""
    return await tools.add_pii_term(term, category, is_pattern)

@mcp.tool()
async def remove_pii_term(term: str) -> dict:
    """Remove a custom PII term."""
    return await tools.remove_pii_term(term)
```

**Files to modify**:
- `src/mcp_server/tools.py` — Add PII management methods
- `src/mcp_server/server.py` — Register tools

**Estimated effort**: 3-4 hours

---

### 7. Golden Set Auto-Population from Analytics

**Current State**: `QueryAnalytics.get_golden_set_suggestions()` identifies good candidates, but adding them to `golden_set.yaml` is manual.

**Impact**: Continuous search quality improvement with minimal friction.

**Implementation**:

```python
# In src/quality/golden_set_manager.py (new file)

import yaml
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

from src.analytics.query_analytics import QueryAnalytics


@dataclass
class GoldenSetEntry:
    """A Golden Set test case."""
    query: str
    expected_file: str
    min_score: float = 0.5
    added_date: str = ""
    source: str = "manual"  # 'manual', 'auto-suggested', 'auto-approved'


class GoldenSetManager:
    """
    Manage Golden Set for search quality testing.
    
    Features:
    - Load/save golden_set.yaml
    - Get suggestions from analytics
    - Add entries with approval workflow
    - Track entry provenance
    """
    
    def __init__(
        self,
        golden_set_path: Optional[Path] = None,
        analytics: Optional[QueryAnalytics] = None
    ):
        self.golden_set_path = golden_set_path or Path("tests/golden_set.yaml")
        self.analytics = analytics or QueryAnalytics()
        self._entries: List[GoldenSetEntry] = []
        self._load()
    
    def _load(self):
        """Load existing golden set."""
        if self.golden_set_path.exists():
            with open(self.golden_set_path) as f:
                data = yaml.safe_load(f) or {}
            
            self._entries = [
                GoldenSetEntry(
                    query=e["query"],
                    expected_file=e["expected_file"],
                    min_score=e.get("min_score", 0.5),
                    added_date=e.get("added_date", ""),
                    source=e.get("source", "manual")
                )
                for e in data.get("test_cases", [])
            ]
    
    def _save(self):
        """Save golden set to file."""
        data = {
            "test_cases": [
                {
                    "query": e.query,
                    "expected_file": e.expected_file,
                    "min_score": e.min_score,
                    "added_date": e.added_date,
                    "source": e.source
                }
                for e in self._entries
            ]
        }
        
        with open(self.golden_set_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    def get_suggestions(self, limit: int = 10) -> List[Dict]:
        """Get suggested additions from analytics."""
        suggestions = self.analytics.get_golden_set_suggestions(limit=limit * 2)
        
        # Filter out existing entries
        existing_queries = {e.query.lower() for e in self._entries}
        
        return [
            s for s in suggestions
            if s["query"].lower() not in existing_queries
        ][:limit]
    
    def add_entry(
        self,
        query: str,
        expected_file: str,
        min_score: float = 0.5,
        source: str = "manual"
    ) -> bool:
        """Add a new golden set entry."""
        # Check for duplicate
        if any(e.query.lower() == query.lower() for e in self._entries):
            return False
        
        entry = GoldenSetEntry(
            query=query,
            expected_file=expected_file,
            min_score=min_score,
            added_date=datetime.now().isoformat(),
            source=source
        )
        
        self._entries.append(entry)
        self._save()
        return True
    
    def approve_suggestion(self, query: str) -> bool:
        """Approve a suggested entry (from analytics)."""
        suggestions = self.get_suggestions(limit=50)
        
        for s in suggestions:
            if s["query"].lower() == query.lower():
                return self.add_entry(
                    query=s["query"],
                    expected_file=s["expected_file"],
                    min_score=0.5,
                    source="auto-approved"
                )
        
        return False
    
    def remove_entry(self, query: str) -> bool:
        """Remove an entry by query."""
        for i, e in enumerate(self._entries):
            if e.query.lower() == query.lower():
                self._entries.pop(i)
                self._save()
                return True
        return False
    
    def get_all_entries(self) -> List[Dict]:
        """Get all golden set entries."""
        return [
            {
                "query": e.query,
                "expected_file": e.expected_file,
                "min_score": e.min_score,
                "added_date": e.added_date,
                "source": e.source
            }
            for e in self._entries
        ]
    
    def get_stats(self) -> Dict:
        """Get golden set statistics."""
        by_source = {}
        for e in self._entries:
            by_source[e.source] = by_source.get(e.source, 0) + 1
        
        return {
            "total_entries": len(self._entries),
            "by_source": by_source,
            "pending_suggestions": len(self.get_suggestions())
        }
```

**MCP Tools**:

```python
# In src/mcp_server/tools.py

async def get_golden_set_suggestions(self) -> Dict[str, Any]:
    """Get suggested additions to the search quality Golden Set."""
    from src.quality.golden_set_manager import GoldenSetManager
    
    manager = GoldenSetManager()
    suggestions = manager.get_suggestions(limit=10)
    stats = manager.get_stats()
    
    return {
        "suggestions": suggestions,
        "current_stats": stats
    }

async def approve_golden_set_entry(self, query: str) -> Dict[str, Any]:
    """Approve a suggested Golden Set entry."""
    from src.quality.golden_set_manager import GoldenSetManager
    
    manager = GoldenSetManager()
    success = manager.approve_suggestion(query)
    
    return {
        "approved": success,
        "query": query,
        "new_total": len(manager.get_all_entries())
    }
```

**Files to create/modify**:
- `src/quality/golden_set_manager.py` — New file
- `src/mcp_server/tools.py` — Add methods
- `src/mcp_server/server.py` — Register tools

**Estimated effort**: 4-6 hours

---

## P2: Quality of Life Improvements

### 8. Proactive Ingestion Suggestions (Gaps Analysis)

**Current State**: System waits for files to appear in Inbox.

**Impact**: System actively suggests what to add based on folder structure and search patterns.

**Implementation**:

```python
# In src/analytics/gaps_analyzer.py (new file)

from pathlib import Path
from typing import List, Dict, Optional
from collections import Counter
from dataclasses import dataclass

from src.analytics.query_analytics import QueryAnalytics


@dataclass
class KnowledgeGap:
    """An identified gap in the knowledge base."""
    topic: str
    evidence: str
    confidence: float  # 0-1
    suggested_action: str


class GapsAnalyzer:
    """
    Identify gaps in the knowledge base.
    
    Analyzes:
    - Folder structure vs content distribution
    - Failed search queries
    - Topic coverage imbalances
    - User focus areas with sparse content
    """
    
    def __init__(
        self,
        vault_path: Path,
        archive_path: Path,
        analytics: Optional[QueryAnalytics] = None
    ):
        self.vault_path = vault_path
        self.archive_path = archive_path
        self.analytics = analytics or QueryAnalytics()
    
    def analyze_folder_distribution(self) -> Dict[str, int]:
        """Count documents per folder in archive."""
        distribution = Counter()
        
        for folder in self.archive_path.rglob("*"):
            if folder.is_dir():
                file_count = len(list(folder.glob("*.*")))
                if file_count > 0:
                    relative = folder.relative_to(self.archive_path)
                    distribution[str(relative)] = file_count
        
        return dict(distribution)
    
    def identify_sparse_folders(self, threshold: int = 3) -> List[str]:
        """Find folders with fewer than threshold documents."""
        distribution = self.analyze_folder_distribution()
        return [folder for folder, count in distribution.items() if count < threshold]
    
    def identify_search_gaps(self) -> List[KnowledgeGap]:
        """Find topics users search for but get poor results."""
        failed_queries = self.analytics.get_failed_queries(limit=20)
        
        gaps = []
        for query in failed_queries:
            gaps.append(KnowledgeGap(
                topic=query.query,
                evidence=f"Searched {query.timestamp}, score: {query.top_result_score:.2f}",
                confidence=1.0 - query.top_result_score,  # Higher confidence for lower scores
                suggested_action=f"Add documents about '{query.query}'"
            ))
        
        return gaps
    
    def identify_imbalances(self) -> List[KnowledgeGap]:
        """Find topic areas with imbalanced coverage."""
        distribution = self.analyze_folder_distribution()
        
        if not distribution:
            return []
        
        avg_count = sum(distribution.values()) / len(distribution)
        gaps = []
        
        for folder, count in distribution.items():
            if count < avg_count * 0.3:  # Less than 30% of average
                gaps.append(KnowledgeGap(
                    topic=folder,
                    evidence=f"Only {count} documents vs {avg_count:.0f} average",
                    confidence=0.7,
                    suggested_action=f"Consider adding more content to '{folder}'"
                ))
        
        return gaps
    
    def get_comprehensive_analysis(self) -> Dict[str, Any]:
        """Get full gaps analysis."""
        search_gaps = self.identify_search_gaps()
        imbalance_gaps = self.identify_imbalances()
        sparse_folders = self.identify_sparse_folders()
        
        all_gaps = search_gaps + imbalance_gaps
        all_gaps.sort(key=lambda g: g.confidence, reverse=True)
        
        return {
            "search_gaps": [
                {"topic": g.topic, "evidence": g.evidence, "action": g.suggested_action}
                for g in search_gaps[:5]
            ],
            "sparse_areas": sparse_folders[:10],
            "imbalances": [
                {"topic": g.topic, "evidence": g.evidence, "action": g.suggested_action}
                for g in imbalance_gaps[:5]
            ],
            "top_recommendations": [
                {"topic": g.topic, "action": g.suggested_action, "confidence": g.confidence}
                for g in all_gaps[:5]
            ]
        }
```

**MCP Tool**:

```python
async def analyze_knowledge_gaps(self) -> Dict[str, Any]:
    """Analyze the knowledge base for gaps and suggest additions."""
    from src.analytics.gaps_analyzer import GapsAnalyzer
    from src.config import VAULT_PATH, ARCHIVE_PATH
    
    analyzer = GapsAnalyzer(VAULT_PATH, ARCHIVE_PATH)
    return analyzer.get_comprehensive_analysis()
```

**Files to create/modify**:
- `src/analytics/gaps_analyzer.py` — New file
- `src/mcp_server/tools.py` — Add method
- `src/mcp_server/server.py` — Register tool

**Estimated effort**: 4-6 hours

---

### 9. Document Versioning and Change Detection

**Current State**: Re-ingesting a file overwrites previous content without tracking changes.

**Impact**: Track document evolution, especially for annually-updated materials like certification guides.

**Implementation**:

```python
# In src/versioning/document_versions.py (new file)

import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass
import difflib


@dataclass
class DocumentVersion:
    """A version of a document."""
    document_id: str
    version: int
    content_hash: str
    ingested_at: str
    source_path: str
    file_size: int
    summary: Optional[str] = None
    changes_from_previous: Optional[str] = None


class DocumentVersionStore:
    """
    Track document versions and changes over time.
    
    Stores content hashes and diff summaries, not full content.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / ".pkm" / "versions.db"
        self._init_db()
    
    def _init_db(self):
        """Initialize version tracking schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                source_path TEXT,
                file_size INTEGER,
                summary TEXT,
                changes_from_previous TEXT,
                UNIQUE(document_id, version)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_versions_docid 
            ON document_versions(document_id)
        """)
        
        conn.commit()
        conn.close()
    
    def compute_hash(self, content: str) -> str:
        """Compute content hash."""
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_latest_version(self, document_id: str) -> Optional[DocumentVersion]:
        """Get the most recent version of a document."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT document_id, version, content_hash, ingested_at, 
                   source_path, file_size, summary, changes_from_previous
            FROM document_versions
            WHERE document_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (document_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return DocumentVersion(*row)
        return None
    
    def is_changed(self, document_id: str, content: str) -> bool:
        """Check if content differs from latest version."""
        latest = self.get_latest_version(document_id)
        if not latest:
            return True  # New document
        
        current_hash = self.compute_hash(content)
        return current_hash != latest.content_hash
    
    def compute_diff_summary(
        self,
        old_content: str,
        new_content: str,
        max_lines: int = 10
    ) -> str:
        """Generate a human-readable diff summary."""
        old_lines = old_content.split('\n')
        new_lines = new_content.split('\n')
        
        differ = difflib.unified_diff(old_lines, new_lines, lineterm='')
        diff_lines = list(differ)
        
        if not diff_lines:
            return "No changes detected"
        
        # Count additions and deletions
        additions = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
        deletions = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
        
        summary = f"Changes: +{additions} lines, -{deletions} lines"
        
        # Include first few changed lines
        changed = [l for l in diff_lines if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))]
        if changed:
            preview = changed[:max_lines]
            summary += "\n\nPreview:\n" + "\n".join(preview)
            if len(changed) > max_lines:
                summary += f"\n... and {len(changed) - max_lines} more changes"
        
        return summary
    
    def record_version(
        self,
        document_id: str,
        content: str,
        source_path: str,
        file_size: int,
        summary: Optional[str] = None,
        old_content: Optional[str] = None
    ) -> DocumentVersion:
        """Record a new version of a document."""
        content_hash = self.compute_hash(content)
        
        # Get next version number
        latest = self.get_latest_version(document_id)
        version = (latest.version + 1) if latest else 1
        
        # Compute changes if we have old content
        changes = None
        if old_content and version > 1:
            changes = self.compute_diff_summary(old_content, content)
        
        # Store
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO document_versions 
            (document_id, version, content_hash, ingested_at, source_path, 
             file_size, summary, changes_from_previous)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            document_id, version, content_hash, datetime.now().isoformat(),
            source_path, file_size, summary, changes
        ))
        
        conn.commit()
        conn.close()
        
        return DocumentVersion(
            document_id=document_id,
            version=version,
            content_hash=content_hash,
            ingested_at=datetime.now().isoformat(),
            source_path=source_path,
            file_size=file_size,
            summary=summary,
            changes_from_previous=changes
        )
    
    def get_version_history(self, document_id: str) -> List[DocumentVersion]:
        """Get all versions of a document."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT document_id, version, content_hash, ingested_at,
                   source_path, file_size, summary, changes_from_previous
            FROM document_versions
            WHERE document_id = ?
            ORDER BY version DESC
        """, (document_id,))
        
        versions = [DocumentVersion(*row) for row in cursor.fetchall()]
        conn.close()
        
        return versions
```

**Integration with executor.py**:

```python
# In src/executor.py, update _index_in_rag()

from src.versioning.document_versions import DocumentVersionStore

def _index_in_rag(text: str, file_name: str, metadata: dict) -> None:
    """Chunk, embed, and store document text in the LanceDB vector database."""
    
    # ... existing code ...
    
    # Check for version changes
    version_store = DocumentVersionStore()
    
    if version_store.is_changed(document_id, text):
        # Get old content for diff (if exists)
        latest = version_store.get_latest_version(document_id)
        old_content = None
        
        if latest:
            # Could fetch old content from RAG if needed
            logger.info(f"Document {file_name} has changed since version {latest.version}")
        
        # Record new version
        version = version_store.record_version(
            document_id=document_id,
            content=text,
            source_path=file_name,
            file_size=len(text),
            summary=metadata.get("summary"),
            old_content=old_content
        )
        
        logger.info(f"Recorded version {version.version} for {file_name}")
        if version.changes_from_previous:
            logger.info(f"Changes: {version.changes_from_previous[:200]}...")
    else:
        logger.info(f"Document {file_name} unchanged, skipping re-index")
        return  # Skip if unchanged
    
    # ... rest of existing indexing code ...
```

**MCP Tool**:

```python
async def get_document_history(self, document_id: str) -> Dict[str, Any]:
    """Get version history for a document."""
    from src.versioning.document_versions import DocumentVersionStore
    
    store = DocumentVersionStore()
    versions = store.get_version_history(document_id)
    
    return {
        "document_id": document_id,
        "total_versions": len(versions),
        "versions": [
            {
                "version": v.version,
                "ingested_at": v.ingested_at,
                "source_path": v.source_path,
                "changes": v.changes_from_previous
            }
            for v in versions
        ]
    }
```

**Files to create/modify**:
- `src/versioning/document_versions.py` — New file
- `src/executor.py` — Integrate version checking
- `src/mcp_server/tools.py` — Add history tool

**Estimated effort**: 6-8 hours

---

### 10. Sorting Rules Enhancement: Pattern Learning

**Current State**: `sorting_rules.yaml` is static. LLM suggestions don't adapt to folder structure changes.

**Impact**: System learns your actual organization patterns, not just explicit rules.

**Implementation**:

```python
# In src/classification/learned_rules.py (new file)

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from collections import Counter
from datetime import datetime


class LearnedRulesManager:
    """
    Learn organization patterns from user corrections.
    
    Builds implicit rules from:
    - Folder corrections (category X -> folder Y)
    - Filename patterns (documents about X use naming convention Y)
    - Sensitivity patterns (category X often marked sensitive)
    """
    
    def __init__(
        self,
        rules_path: Optional[Path] = None,
        corrections_path: Optional[Path] = None
    ):
        self.rules_path = rules_path or Path("sorting_rules.yaml")
        self.corrections_path = corrections_path or Path("corrections_log.json")
        self.learned_rules_path = Path.home() / ".pkm" / "learned_rules.yaml"
    
    def analyze_corrections(self) -> Dict[str, Dict]:
        """Analyze correction history to derive patterns."""
        import json
        
        if not self.corrections_path.exists():
            return {}
        
        with open(self.corrections_path) as f:
            corrections = json.load(f)
        
        patterns = {
            "folder_mappings": Counter(),  # (from_folder, to_folder) -> count
            "category_to_folder": Counter(),  # (category, folder) -> count
            "sensitivity_categories": Counter(),  # category -> sensitive_count
        }
        
        for c in corrections:
            corr = c.get("corrections", {})
            
            # Folder corrections
            if "target_folder" in corr:
                from_folder = corr["target_folder"]["ai"]
                to_folder = corr["target_folder"]["human"]
                patterns["folder_mappings"][(from_folder, to_folder)] += 1
            
            # Category -> folder patterns
            if "category" in corr or "target_folder" in corr:
                category = corr.get("category", {}).get("human") or c.get("summary", "")[:50]
                folder = corr.get("target_folder", {}).get("human", "")
                if category and folder:
                    patterns["category_to_folder"][(category, folder)] += 1
            
            # Sensitivity patterns
            if "pii_override" in corr:
                # Extract category from summary or original file
                category = c.get("summary", "")[:50]
                if corr["pii_override"]["human"] == "sensitive":
                    patterns["sensitivity_categories"][category] += 1
        
        return patterns
    
    def generate_learned_rules(self, min_frequency: int = 2) -> Dict:
        """Generate rules from patterns that appear at least min_frequency times."""
        patterns = self.analyze_corrections()
        
        rules = {
            "folder_redirects": {},
            "category_defaults": {},
            "sensitive_categories": [],
            "generated_at": datetime.now().isoformat(),
            "source": "auto-learned from corrections"
        }
        
        # Folder redirects (when AI suggests X, user usually picks Y)
        for (from_f, to_f), count in patterns["folder_mappings"].most_common():
            if count >= min_frequency:
                rules["folder_redirects"][from_f] = {
                    "target": to_f,
                    "confidence": min(0.9, count / 10),
                    "occurrences": count
                }
        
        # Category defaults
        for (cat, folder), count in patterns["category_to_folder"].most_common():
            if count >= min_frequency and cat not in rules["category_defaults"]:
                rules["category_defaults"][cat] = {
                    "folder": folder,
                    "confidence": min(0.9, count / 10),
                    "occurrences": count
                }
        
        # Sensitive categories
        for cat, count in patterns["sensitivity_categories"].most_common():
            if count >= min_frequency:
                rules["sensitive_categories"].append({
                    "pattern": cat,
                    "occurrences": count
                })
        
        return rules
    
    def save_learned_rules(self):
        """Generate and save learned rules."""
        rules = self.generate_learned_rules()
        
        self.learned_rules_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.learned_rules_path, 'w') as f:
            yaml.dump(rules, f, default_flow_style=False)
        
        return rules
    
    def get_folder_suggestion(self, ai_suggestion: str, category: str) -> Optional[str]:
        """Get potentially better folder based on learned patterns."""
        if not self.learned_rules_path.exists():
            return None
        
        with open(self.learned_rules_path) as f:
            rules = yaml.safe_load(f) or {}
        
        # Check folder redirects
        if ai_suggestion in rules.get("folder_redirects", {}):
            redirect = rules["folder_redirects"][ai_suggestion]
            if redirect.get("confidence", 0) >= 0.5:
                return redirect["target"]
        
        # Check category defaults
        if category in rules.get("category_defaults", {}):
            default = rules["category_defaults"][category]
            if default.get("confidence", 0) >= 0.5:
                return default["folder"]
        
        return None
    
    def should_mark_sensitive(self, summary: str, category: str) -> bool:
        """Check if document should likely be marked sensitive based on patterns."""
        if not self.learned_rules_path.exists():
            return False
        
        with open(self.learned_rules_path) as f:
            rules = yaml.safe_load(f) or {}
        
        for sensitive in rules.get("sensitive_categories", []):
            pattern = sensitive.get("pattern", "").lower()
            if pattern in summary.lower() or pattern in category.lower():
                return True
        
        return False
```

**Integration with intelligence.py**:

```python
# In src/intelligence.py

from src.classification.learned_rules import LearnedRulesManager

def analyze_document(text: str, file_name: str) -> dict:
    # ... existing LLM analysis ...
    
    # Apply learned rules to potentially improve suggestion
    rules_manager = LearnedRulesManager()
    
    ai_folder = result.get("target_folder", "")
    ai_category = result.get("category", "")
    
    learned_folder = rules_manager.get_folder_suggestion(ai_folder, ai_category)
    if learned_folder:
        result["target_folder"] = learned_folder
        result["folder_source"] = "learned_pattern"
        logger.info(f"Applied learned rule: {ai_folder} -> {learned_folder}")
    
    # Check sensitivity
    if rules_manager.should_mark_sensitive(result.get("summary", ""), ai_category):
        result["is_sensitive"] = True
        result["sensitivity_source"] = "learned_pattern"
        logger.info(f"Applied learned sensitivity rule for {file_name}")
    
    return result
```

**Files to create/modify**:
- `src/classification/learned_rules.py` — New file
- `src/intelligence.py` — Integrate learned rules

**Estimated effort**: 6-8 hours

---

## P3: Future Considerations (Backlog)

### 11. Multi-Vault Support

Support multiple Obsidian vaults with different purposes (Work, Personal, Research).

### 12. Collaborative Features

Shared PKM with family members, permission levels for sensitive content.

### 13. External Integrations

- Readwise sync for highlights
- Pocket/Instapaper for saved articles
- Calendar integration for date-aware retrieval

### 14. Advanced Retrieval

- Query rewriting with context
- Retrieval-augmented generation prompts
- Conversational search with follow-ups

### 15. Mobile Companion App

iOS Shortcut or lightweight app for quick capture to Inbox.

---

## Implementation Timeline

### Weeks 1-2: P0 Priorities

| Task | Effort | Owner |
|------|--------|-------|
| Wire Knowledge Graph to MCP | 4-6h | — |
| Database Health MCP Tools | 2-3h | — |
| Quick wins from existing code | 4h | — |

### Weeks 3-4: P1 Batch 1

| Task | Effort | Owner |
|------|--------|-------|
| Query Analytics → Episodic Memory | 8-12h | — |
| Obsidian Backlinks | 6-8h | — |

### Weeks 5-6: P1 Batch 2

| Task | Effort | Owner |
|------|--------|-------|
| Dashboard Enhancements | 6-8h | — |
| PII Dictionary MCP Tools | 3-4h | — |
| Golden Set Auto-Population | 4-6h | — |

### Weeks 7-10: P2 Features

| Task | Effort | Owner |
|------|--------|-------|
| Gaps Analysis | 4-6h | — |
| Document Versioning | 6-8h | — |
| Learned Rules | 6-8h | — |

---

## Success Metrics

### Search Quality
- Golden Set pass rate > 90%
- Failed query rate < 10%
- Average top result score > 0.7

### User Efficiency
- Average corrections per batch < 20%
- Bulk operations usage > 50% of reviews
- Time to review 50 documents < 15 minutes

### System Health
- Database fragmentation < 20%
- Memory usage during ingestion < 75%
- No ingestion failures due to resources

### Knowledge Coverage
- Identified gaps addressed within 30 days
- Sparse folders filled to average
- Search pattern diversity increasing

---

## References

- `docs/PHASE_6_EPISODIC_MEMORY.md` — Detailed Phase 6 design
- `architecture/` — System design documents
- `src/` — Implementation reference

---

*Document created 2026-02-01 during comprehensive codebase review.*
