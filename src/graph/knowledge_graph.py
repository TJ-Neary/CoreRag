"""
Lightweight GraphRAG: Co-occurrence Knowledge Graph

Extracts entities and relationships from documents to enable
relationship-aware retrieval.

Vectors find "similar things" but miss relationships.
This graph layer answers: "How does X relate to Y?"
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.exceptions import DatabaseError as CoreRagDatabaseError

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

    subject: str  # Entity name
    predicate: str  # Relationship type
    object: str  # Entity name
    document_id: str
    confidence: float = 1.0
    context: str = ""  # Snippet where relationship was found


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
            self.subject.lower() == other.subject.lower()
            and self.predicate.lower() == other.predicate.lower()
            and self.object.lower() == other.object.lower()
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

    async def extract(self, text: str, document_id: str) -> Tuple[List[Entity], List[Relationship]]:
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

    def extract_sync(self, text: str, document_id: str) -> Tuple[List[Entity], List[Relationship]]:
        """Synchronous extraction using regex patterns only (no LLM)."""
        return self._extract_with_patterns(text, document_id)

    async def _extract_with_llm(
        self, text: str, document_id: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract using LLM."""
        try:
            prompt = self.EXTRACTION_PROMPT.format(text=text[:4000])
            response = await self.llm.generate(prompt, max_tokens=1000)

            # Parse JSON from response
            # Find JSON block in response
            import re

            json_match = re.search(r"\{[\s\S]*\}", response)
            if not json_match:
                return [], []

            data = json.loads(json_match.group())

            entities = [
                Entity(
                    name=e["name"],
                    type=e.get("type", "concept"),
                    document_id=document_id,
                    confidence=e.get("confidence", 0.8),
                )
                for e in data.get("entities", [])
            ]

            relationships = [
                Relationship(
                    subject=r["subject"],
                    predicate=r["predicate"],
                    object=r["object"],
                    document_id=document_id,
                    confidence=r.get("confidence", 0.8),
                )
                for r in data.get("relationships", [])
            ]

            return entities, relationships

        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}, falling back to patterns")
            return self._extract_with_patterns(text, document_id)

    def _extract_with_patterns(
        self, text: str, document_id: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract using regex patterns (fallback)."""
        import re

        entities = []
        relationships = []

        # Extract capitalized phrases (potential named entities)
        # Pattern: 2-4 capitalized words in sequence
        cap_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
        for match in re.finditer(cap_pattern, text):
            name = match.group(1)
            if len(name) > 3:  # Skip short matches
                entities.append(
                    Entity(
                        name=name,
                        type="concept",  # Can't determine type without LLM
                        document_id=document_id,
                        confidence=0.5,
                    )
                )

        # Extract common relationship patterns
        rel_patterns = [
            (r"(\w+)\s+(?:uses?|using)\s+(\w+)", "uses"),
            (r"(\w+)\s+(?:depends?\s+on|requires?)\s+(\w+)", "depends_on"),
            (r"(\w+)\s+(?:created?|authored?|wrote)\s+(\w+)", "created"),
            (r"(\w+)\s+(?:is\s+part\s+of|belongs?\s+to)\s+(\w+)", "part_of"),
            (r"(\w+)\s+(?:mentions?|references?)\s+(\w+)", "mentions"),
        ]

        for pattern, predicate in rel_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                relationships.append(
                    Relationship(
                        subject=match.group(1),
                        predicate=predicate,
                        object=match.group(2),
                        document_id=document_id,
                        confidence=0.4,
                    )
                )

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
        """Initialize database schema with bitemporal fields."""
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
                first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                mention_count INTEGER DEFAULT 1,
                confidence_score REAL DEFAULT 1.0,
                UNIQUE(name, type, document_id)
            )
        """)

        # Relationships table (triples) with bitemporal tracking
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
                when_true TEXT DEFAULT '',
                when_learned TEXT DEFAULT CURRENT_TIMESTAMP,
                superseded_by INTEGER DEFAULT NULL,
                UNIQUE(subject, predicate, object, document_id)
            )
        """)

        # Indices for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_subject ON relationships(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_object ON relationships(object)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_predicate ON relationships(predicate)")

        # Migrate existing tables — add new columns if they don't exist
        self._migrate_schema(cursor)

        conn.commit()
        conn.close()

    def _migrate_schema(self, cursor: sqlite3.Cursor) -> None:
        """Add bitemporal columns to existing tables if missing.

        Uses constant defaults in ALTER TABLE because some SQLite versions
        reject CURRENT_TIMESTAMP as a non-constant default. Backfills
        existing rows with created_at value after adding columns.
        """
        # Entity columns — use constant defaults for ALTER TABLE compatibility
        for col, col_type, default in [
            ("first_seen", "TEXT", "''"),
            ("last_seen", "TEXT", "''"),
            ("mention_count", "INTEGER", "1"),
            ("confidence_score", "REAL", "1.0"),
        ]:
            try:
                cursor.execute(
                    f"ALTER TABLE entities ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                # Backfill: set timestamp columns to created_at for existing rows
                if col in ("first_seen", "last_seen"):
                    cursor.execute(f"UPDATE entities SET {col} = created_at WHERE {col} = ''")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Relationship columns
        for col, col_type, default in [
            ("when_true", "TEXT", "''"),
            ("when_learned", "TEXT", "''"),
            ("superseded_by", "INTEGER", "NULL"),
        ]:
            try:
                cursor.execute(
                    f"ALTER TABLE relationships ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                # Backfill: set when_learned to created_at for existing rows
                if col == "when_learned":
                    cursor.execute(f"UPDATE relationships SET {col} = created_at WHERE {col} = ''")
            except sqlite3.OperationalError:
                pass  # Column already exists

    def add_entity(self, entity: Entity):
        """Add an entity to the graph with bitemporal tracking.

        If the entity already exists (same name+type+document_id), updates
        last_seen and increments mention_count instead of replacing.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Try to insert new
            cursor.execute(
                """
                INSERT INTO entities
                    (name, type, document_id, confidence, metadata,
                     first_seen, last_seen, mention_count, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
                (
                    entity.name,
                    entity.type,
                    entity.document_id,
                    entity.confidence,
                    json.dumps(entity.metadata),
                    now,
                    now,
                    entity.confidence,
                ),
            )
        except sqlite3.IntegrityError:
            # Entity exists — update last_seen and increment mention_count
            cursor.execute(
                """
                UPDATE entities
                SET last_seen = ?, mention_count = mention_count + 1,
                    confidence_score = MAX(confidence_score, ?)
                WHERE name = ? AND type = ? AND document_id = ?
            """,
                (now, entity.confidence, entity.name, entity.type, entity.document_id),
            )
        except Exception as e:
            logger.error(f"Error adding entity: {e}")
            raise CoreRagDatabaseError(
                f"Failed to add entity '{entity.name}': {e}", table_name="entities"
            ) from e

        conn.commit()
        conn.close()

    def add_relationship(self, rel: Relationship, when_true: str = ""):
        """Add a relationship to the graph with bitemporal tracking.

        Args:
            rel: Relationship to add.
            when_true: When the fact was true (event time), e.g. "2024-03".
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO relationships
                (subject, predicate, object, document_id, confidence, context,
                 when_true, when_learned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    rel.subject,
                    rel.predicate,
                    rel.object,
                    rel.document_id,
                    rel.confidence,
                    rel.context,
                    when_true,
                    now,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding relationship: {e}")
            raise CoreRagDatabaseError(
                f"Failed to add relationship '{rel.subject} -> {rel.object}': {e}",
                table_name="relationships",
            ) from e
        finally:
            conn.close()

    def add_from_extraction(self, entities: List[Entity], relationships: List[Relationship]):
        """Batch add entities and relationships."""
        for entity in entities:
            self.add_entity(entity)
        for rel in relationships:
            self.add_relationship(rel)

    def get_neighbors(
        self,
        entity_name: str,
        relationship_types: Optional[List[str]] = None,
        direction: str = "both",  # "outgoing", "incoming", "both"
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
                    results.append(
                        {
                            "entity": row[0],
                            "relationship": row[1],
                            "direction": "outgoing",
                            "document_id": row[2],
                            "confidence": row[3],
                        }
                    )

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
                    results.append(
                        {
                            "entity": row[0],
                            "relationship": row[1],
                            "direction": "incoming",
                            "document_id": row[2],
                            "confidence": row[3],
                        }
                    )

        finally:
            conn.close()

        return results

    def find_path(self, start: str, end: str, max_hops: int = 3) -> Optional[List[Triple]]:
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
        queue: deque[tuple[str, list[Triple]]] = deque([(start.lower(), [])])

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
                    new_path = path + [
                        Triple(subject=current, predicate=neighbor["relationship"], object=entity)
                    ]
                    queue.append((entity, new_path))

        return None

    def supersede_relationship(self, old_id: int, new_id: int) -> None:
        """Mark an old relationship as superseded by a newer one."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE relationships SET superseded_by = ? WHERE id = ?",
                (new_id, old_id),
            )
            conn.commit()
        finally:
            conn.close()

    def apply_confidence_decay(self, half_life_days: int = 365) -> int:
        """Reduce confidence of stale entities based on time since last seen.

        Uses exponential decay: confidence *= 2^(-days_since_last_seen / half_life).

        Args:
            half_life_days: Days for confidence to halve.

        Returns:
            Number of entities updated.
        """
        import math
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        updated = 0

        try:
            cursor.execute("SELECT id, last_seen, confidence_score FROM entities")
            rows = cursor.fetchall()

            for row_id, last_seen_str, current_conf in rows:
                if not last_seen_str:
                    continue
                try:
                    last_seen = datetime.fromisoformat(last_seen_str)
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=timezone.utc)
                    days_elapsed = (now - last_seen).days
                    if days_elapsed <= 0:
                        continue

                    decay = math.pow(2, -days_elapsed / half_life_days)
                    new_conf = round(current_conf * decay, 4)

                    if abs(new_conf - current_conf) > 0.001:
                        cursor.execute(
                            "UPDATE entities SET confidence_score = ? WHERE id = ?",
                            (new_conf, row_id),
                        )
                        updated += 1
                except (ValueError, TypeError):
                    continue

            conn.commit()
        finally:
            conn.close()

        logger.info(f"Confidence decay: updated {updated} entities (half_life={half_life_days}d)")
        return updated

    def get_entity_timeline(self, name: str) -> List[Dict]:
        """Get chronological view of an entity's appearances across documents.

        Args:
            name: Entity name to look up.

        Returns:
            List of dicts with document_id, type, first_seen, last_seen, mention_count.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT document_id, type, first_seen, last_seen,
                       mention_count, confidence_score
                FROM entities
                WHERE LOWER(name) = ?
                ORDER BY first_seen
            """,
                (name.lower(),),
            )

            return [
                {
                    "document_id": row[0],
                    "type": row[1],
                    "first_seen": row[2],
                    "last_seen": row[3],
                    "mention_count": row[4],
                    "confidence_score": row[5],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def search_entities(
        self, query: str, min_confidence: float = 0.0, limit: int = 20
    ) -> List[Dict]:
        """Search entities by name with optional confidence threshold.

        Args:
            query: Search term (case-insensitive LIKE match).
            min_confidence: Minimum confidence_score filter.
            limit: Max results.

        Returns:
            List of entity dicts.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT DISTINCT name, type, confidence_score, mention_count, last_seen
                FROM entities
                WHERE LOWER(name) LIKE ? AND confidence_score >= ?
                ORDER BY confidence_score DESC, mention_count DESC
                LIMIT ?
            """,
                (f"%{query.lower()}%", min_confidence, limit),
            )

            return [
                {
                    "name": row[0],
                    "type": row[1],
                    "confidence_score": row[2],
                    "mention_count": row[3],
                    "last_seen": row[4],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

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
                "relationship_types": rel_types,
            }

        finally:
            conn.close()

    def get_all_entities(self) -> List[Dict]:
        """Return all distinct entities from the graph."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT name, type, confidence_score, mention_count FROM entities"
            )
            return [
                {"name": row[0], "type": row[1], "confidence": row[2], "mention_count": row[3]}
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def build_entity_index(self, embedding_service) -> int:
        """Embed all entity names into a LanceDB table for semantic discovery."""
        import lancedb

        from src import config

        entities = self.get_all_entities()
        if not entities:
            return 0

        texts = [f"{e['name']}: {e.get('type', '')}" for e in entities]
        vectors = embedding_service.embed_documents(texts, show_progress=False)

        data = [
            {
                "id": e["name"],
                "type": e.get("type", ""),
                "vector": v,
                "mention_count": e.get("mention_count", 1),
            }
            for e, v in zip(entities, vectors)
        ]

        db = lancedb.connect(str(config.DB_PATH))
        try:
            db.drop_table("entity_vectors")
        except Exception:
            pass
        db.create_table("entity_vectors", data)
        logger.info(f"Entity index built: {len(data)} entities embedded")
        return len(data)

    def search_entities_semantic(self, query: str, embedding_service, k: int = 10) -> List[Dict]:
        """Find entities semantically related to query, then traverse graph from those."""
        import lancedb

        from src import config

        query_vector = embedding_service.embed_query(query)

        db = lancedb.connect(str(config.DB_PATH))
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if "entity_vectors" not in db.table_names():
                return []

        table = db.open_table("entity_vectors")
        results = table.search(query_vector).limit(k).to_list()

        enriched = []
        for r in results:
            entity_name = r["id"]
            neighbors = self.get_neighbors(entity_name)
            enriched.append(
                {
                    "entity": entity_name,
                    "type": r.get("type", ""),
                    "similarity": max(0.0, 1.0 - r.get("_distance", 0)),
                    "relationships": neighbors,
                }
            )
        return enriched

    def find_related_documents(self, document_id: str, limit: int = 20) -> List[Dict]:
        """
        Find documents that share entities with the given document.

        Returns list of dicts with document_id and shared_entities.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT e2.document_id, GROUP_CONCAT(DISTINCT e2.name)
                FROM entities e1
                JOIN entities e2 ON LOWER(e1.name) = LOWER(e2.name)
                    AND e1.document_id != e2.document_id
                WHERE e1.document_id = ?
                GROUP BY e2.document_id
                ORDER BY COUNT(DISTINCT e2.name) DESC
                LIMIT ?
            """,
                (document_id, limit),
            )

            return [
                {"document_id": row[0], "shared_entities": row[1].split(",")}
                for row in cursor.fetchall()
            ]
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
        **kwargs,
    ) -> Dict:
        """
        Search with graph-based expansion.

        1. Vector search for query
        2. Extract entities from top results
        3. Find related entities via graph
        4. Include documents mentioning related entities
        """
        # Step 1: Initial vector search
        initial_results = await self.retriever.search(
            query=query, query_vector=query_vector, k=k, **kwargs
        )

        # Step 2: Extract entities mentioned in results
        mentioned_entities = set()
        for r in initial_results:
            doc_id = r.get("document_id")
            # Query graph for entities in this document
            conn = sqlite3.connect(self.graph.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT name FROM entities WHERE document_id = ?", (doc_id,))
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
                "related_documents": list(new_doc_ids)[:5],
            },
        }
