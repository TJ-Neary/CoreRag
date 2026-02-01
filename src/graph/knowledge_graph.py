"""
Lightweight GraphRAG: Co-occurrence Knowledge Graph

Extracts entities and relationships from documents to enable
relationship-aware retrieval.

Vectors find "similar things" but miss relationships.
This graph layer answers: "How does X relate to Y?"
"""

import logging
import sqlite3
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Set
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """An extracted entity."""
    name: str
    type: str  # person, project, technology, concept, organization
    document_id: str
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class Relationship:
    """A relationship between entities."""
    subject: str           # Entity name
    predicate: str        # Relationship type
    object: str           # Entity name
    document_id: str
    confidence: float = 1.0
    context: str = ""     # Snippet where relationship was found


@dataclass
class Triple:
    """Subject-Predicate-Object triple."""
    subject: str
    predicate: str
    object: str

    def __hash__(self):
        return hash((self.subject.lower(), self.predicate.lower(), self.object.lower()))

    def __eq__(self, other):
        if not isinstance(other, Triple):
            return False
        return (
            self.subject.lower() == other.subject.lower() and
            self.predicate.lower() == other.predicate.lower() and
            self.object.lower() == other.object.lower()
        )


class EntityExtractor:
    """
    Extracts entities and relationships from text.

    Uses a small local LLM (Llama-3.2-3B or Qwen-2.5-7B) for extraction.
    Falls back to regex patterns if LLM unavailable.
    """

    EXTRACTION_PROMPT = """Extract entities and relationships from this text.

Text:
{text}

Output JSON with:
- entities: [{"name": "...", "type": "person|project|technology|concept|organization"}]
- relationships: [{"subject": "...", "predicate": "...", "object": "..."}]

Focus on:
- Named entities (people, projects, technologies)
- Important relationships (created, uses, depends_on, authored_by, mentions)
- Keep only the top 5 most important entities and relationships

JSON:"""

    def __init__(self, llm=None):
        """
        Args:
            llm: Local LLM for extraction (optional, uses regex fallback)
        """
        self.llm = llm

    async def extract(
        self,
        text: str,
        document_id: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """
        Extract entities and relationships from text.

        Args:
            text: Document text
            document_id: Source document ID

        Returns:
            Tuple of (entities, relationships)
        """
        if self.llm:
            return await self._extract_with_llm(text, document_id)
        else:
            return self._extract_with_patterns(text, document_id)

    async def _extract_with_llm(
        self,
        text: str,
        document_id: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract using LLM."""
        try:
            prompt = self.EXTRACTION_PROMPT.format(text=text[:4000])
            response = await self.llm.generate(prompt, max_tokens=1000)

            # Parse JSON from response
            # Find JSON block in response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return [], []

            data = json.loads(json_match.group())

            entities = [
                Entity(
                    name=e["name"],
                    type=e.get("type", "concept"),
                    document_id=document_id,
                    confidence=e.get("confidence", 0.8)
                )
                for e in data.get("entities", [])
            ]

            relationships = [
                Relationship(
                    subject=r["subject"],
                    predicate=r["predicate"],
                    object=r["object"],
                    document_id=document_id,
                    confidence=r.get("confidence", 0.8)
                )
                for r in data.get("relationships", [])
            ]

            return entities, relationships

        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}, falling back to patterns")
            return self._extract_with_patterns(text, document_id)

    def _extract_with_patterns(
        self,
        text: str,
        document_id: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract using regex patterns (fallback)."""
        import re

        entities = []
        relationships = []

        # Extract capitalized phrases (potential named entities)
        # Pattern: 2-4 capitalized words in sequence
        cap_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b'
        for match in re.finditer(cap_pattern, text):
            name = match.group(1)
            if len(name) > 3:  # Skip short matches
                entities.append(Entity(
                    name=name,
                    type="concept",  # Can't determine type without LLM
                    document_id=document_id,
                    confidence=0.5
                ))

        # Extract common relationship patterns
        rel_patterns = [
            (r'(\w+)\s+(?:uses?|using)\s+(\w+)', 'uses'),
            (r'(\w+)\s+(?:depends?\s+on|requires?)\s+(\w+)', 'depends_on'),
            (r'(\w+)\s+(?:created?|authored?|wrote)\s+(\w+)', 'created'),
            (r'(\w+)\s+(?:is\s+part\s+of|belongs?\s+to)\s+(\w+)', 'part_of'),
            (r'(\w+)\s+(?:mentions?|references?)\s+(\w+)', 'mentions'),
        ]

        for pattern, predicate in rel_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                relationships.append(Relationship(
                    subject=match.group(1),
                    predicate=predicate,
                    object=match.group(2),
                    document_id=document_id,
                    confidence=0.4
                ))

        return entities, relationships


class KnowledgeGraph:
    """
    SQLite-backed knowledge graph for entity relationships.

    Stores entities and relationships extracted from documents.
    Enables queries like: "What entities are related to X?"
    """

    def __init__(self, db_path: Path):
        """
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Entities table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                document_id TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, type, document_id)
            )
        """)

        # Relationships table (triples)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                document_id TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                context TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subject, predicate, object, document_id)
            )
        """)

        # Indices for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_subject ON relationships(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_object ON relationships(object)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_predicate ON relationships(predicate)")

        conn.commit()
        conn.close()

    def add_entity(self, entity: Entity):
        """Add an entity to the graph."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO entities (name, type, document_id, confidence, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (
                entity.name,
                entity.type,
                entity.document_id,
                entity.confidence,
                json.dumps(entity.metadata)
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding entity: {e}")
        finally:
            conn.close()

    def add_relationship(self, rel: Relationship):
        """Add a relationship to the graph."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO relationships
                (subject, predicate, object, document_id, confidence, context)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                rel.subject,
                rel.predicate,
                rel.object,
                rel.document_id,
                rel.confidence,
                rel.context
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding relationship: {e}")
        finally:
            conn.close()

    def add_from_extraction(
        self,
        entities: List[Entity],
        relationships: List[Relationship]
    ):
        """Batch add entities and relationships."""
        for entity in entities:
            self.add_entity(entity)
        for rel in relationships:
            self.add_relationship(rel)

    def get_neighbors(
        self,
        entity_name: str,
        relationship_types: Optional[List[str]] = None,
        direction: str = "both"  # "outgoing", "incoming", "both"
    ) -> List[Dict]:
        """
        Get entities related to a given entity.

        Args:
            entity_name: Entity to find neighbors for
            relationship_types: Filter by relationship type
            direction: Direction of relationships

        Returns:
            List of related entities with relationship info
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        results = []
        name_lower = entity_name.lower()

        try:
            if direction in ("outgoing", "both"):
                query = """
                    SELECT object, predicate, document_id, confidence
                    FROM relationships
                    WHERE LOWER(subject) = ?
                """
                params = [name_lower]

                if relationship_types:
                    placeholders = ",".join("?" * len(relationship_types))
                    query += f" AND predicate IN ({placeholders})"
                    params.extend(relationship_types)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    results.append({
                        "entity": row[0],
                        "relationship": row[1],
                        "direction": "outgoing",
                        "document_id": row[2],
                        "confidence": row[3]
                    })

            if direction in ("incoming", "both"):
                query = """
                    SELECT subject, predicate, document_id, confidence
                    FROM relationships
                    WHERE LOWER(object) = ?
                """
                params = [name_lower]

                if relationship_types:
                    placeholders = ",".join("?" * len(relationship_types))
                    query += f" AND predicate IN ({placeholders})"
                    params.extend(relationship_types)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    results.append({
                        "entity": row[0],
                        "relationship": row[1],
                        "direction": "incoming",
                        "document_id": row[2],
                        "confidence": row[3]
                    })

        finally:
            conn.close()

        return results

    def find_path(
        self,
        start: str,
        end: str,
        max_hops: int = 3
    ) -> Optional[List[Triple]]:
        """
        Find a path between two entities.

        Args:
            start: Starting entity
            end: Ending entity
            max_hops: Maximum relationship hops

        Returns:
            List of triples forming the path, or None if not found
        """
        # BFS to find shortest path
        from collections import deque

        visited = set()
        queue = deque([(start.lower(), [])])

        while queue:
            current, path = queue.popleft()

            if current == end.lower():
                return path

            if current in visited or len(path) >= max_hops:
                continue

            visited.add(current)

            for neighbor in self.get_neighbors(current, direction="both"):
                entity = neighbor["entity"].lower()
                if entity not in visited:
                    new_path = path + [Triple(
                        subject=current,
                        predicate=neighbor["relationship"],
                        object=entity
                    )]
                    queue.append((entity, new_path))

        return None

    def get_stats(self) -> Dict:
        """Get graph statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(DISTINCT name) FROM entities")
            entity_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM relationships")
            rel_count = cursor.fetchone()[0]

            cursor.execute("SELECT type, COUNT(*) FROM entities GROUP BY type")
            entity_types = dict(cursor.fetchall())

            cursor.execute("SELECT predicate, COUNT(*) FROM relationships GROUP BY predicate")
            rel_types = dict(cursor.fetchall())

            return {
                "total_entities": entity_count,
                "total_relationships": rel_count,
                "entity_types": entity_types,
                "relationship_types": rel_types
            }

        finally:
            conn.close()

    def delete_by_document(self, document_id: str):
        """Delete all entities and relationships from a document."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM entities WHERE document_id = ?", (document_id,))
            cursor.execute("DELETE FROM relationships WHERE document_id = ?", (document_id,))
            conn.commit()
            logger.info(f"Deleted graph data for document: {document_id}")
        finally:
            conn.close()


class GraphEnhancedRetrieval:
    """
    Combines vector retrieval with graph traversal.

    When searching for "Project Alpha", also retrieves documents
    that mention entities related to Project Alpha.
    """

    def __init__(self, retriever, graph: KnowledgeGraph):
        self.retriever = retriever
        self.graph = graph

    async def search_with_graph(
        self,
        query: str,
        query_vector: List[float],
        k: int = 5,
        graph_expansion: int = 2,  # How many neighbor hops
        **kwargs
    ) -> List[Dict]:
        """
        Search with graph-based expansion.

        1. Vector search for query
        2. Extract entities from top results
        3. Find related entities via graph
        4. Include documents mentioning related entities
        """
        # Step 1: Initial vector search
        initial_results = await self.retriever.search(
            query=query,
            query_vector=query_vector,
            k=k,
            **kwargs
        )

        # Step 2: Extract entities mentioned in results
        mentioned_entities = set()
        for r in initial_results:
            doc_id = r.get("document_id")
            # Query graph for entities in this document
            conn = sqlite3.connect(self.graph.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT name FROM entities WHERE document_id = ?",
                (doc_id,)
            )
            for row in cursor.fetchall():
                mentioned_entities.add(row[0])
            conn.close()

        # Step 3: Find related entities
        related_doc_ids = set()
        for entity in mentioned_entities:
            neighbors = self.graph.get_neighbors(entity)
            for n in neighbors:
                related_doc_ids.add(n["document_id"])

        # Step 4: Fetch related documents (if not already in results)
        existing_doc_ids = {r.get("document_id") for r in initial_results}
        new_doc_ids = related_doc_ids - existing_doc_ids

        # Could query these documents and add to results
        # For now, return initial results with graph context

        return {
            "results": initial_results,
            "graph_context": {
                "mentioned_entities": list(mentioned_entities),
                "related_documents": list(new_doc_ids)[:5]
            }
        }
