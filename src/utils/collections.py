"""
Collections and organization for PKM.

Enable grouping documents into user-defined collections.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Collection:
    """A user-defined collection of documents."""
    collection_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    document_ids: List[str] = field(default_factory=list)
    color: str = "#808080"  # Display color
    icon: str = "📁"  # Display icon
    parent_id: Optional[str] = None  # For nested collections
    is_smart: bool = False  # Smart collections auto-update based on query
    smart_query: Optional[str] = None
    smart_filters: Dict = field(default_factory=dict)


class CollectionManager:
    """
    Manage document collections.

    Features:
    - Manual collections (user adds documents)
    - Smart collections (auto-populated by query)
    - Nested collections (folders)
    - Collection sharing/export
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize collection manager.

        Args:
            state_dir: Directory for collection storage
        """
        self.state_dir = state_dir or Path.home() / ".pkm" / "collections"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._collections: Dict[str, Collection] = {}
        self._doc_to_collections: Dict[str, Set[str]] = {}  # Reverse index

        self._load_state()

    def create_collection(
        self,
        name: str,
        description: str = "",
        color: str = "#808080",
        icon: str = "📁",
        parent_id: Optional[str] = None
    ) -> Collection:
        """
        Create a new collection.

        Args:
            name: Collection name
            description: Collection description
            color: Display color
            icon: Display icon
            parent_id: Parent collection for nesting

        Returns:
            Created collection
        """
        collection_id = f"col_{len(self._collections)}_{datetime.now().timestamp():.0f}"

        collection = Collection(
            collection_id=collection_id,
            name=name,
            description=description,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            color=color,
            icon=icon,
            parent_id=parent_id
        )

        self._collections[collection_id] = collection
        self._save_state()

        logger.info(f"Created collection: {name}")

        return collection

    def create_smart_collection(
        self,
        name: str,
        query: str,
        filters: Optional[Dict] = None,
        description: str = "",
        color: str = "#4A90D9",
        icon: str = "🔍"
    ) -> Collection:
        """
        Create a smart collection that auto-updates.

        Args:
            name: Collection name
            query: Search query to populate collection
            filters: Search filters
            description: Collection description
            color: Display color
            icon: Display icon

        Returns:
            Created smart collection
        """
        collection_id = f"smart_{len(self._collections)}_{datetime.now().timestamp():.0f}"

        collection = Collection(
            collection_id=collection_id,
            name=name,
            description=description,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            color=color,
            icon=icon,
            is_smart=True,
            smart_query=query,
            smart_filters=filters or {}
        )

        self._collections[collection_id] = collection
        self._save_state()

        logger.info(f"Created smart collection: {name}")

        return collection

    def get_collection(self, collection_id: str) -> Optional[Collection]:
        """Get a collection by ID."""
        return self._collections.get(collection_id)

    def get_all_collections(self) -> List[Collection]:
        """Get all collections."""
        return list(self._collections.values())

    def get_root_collections(self) -> List[Collection]:
        """Get top-level collections (no parent)."""
        return [c for c in self._collections.values() if c.parent_id is None]

    def get_children(self, collection_id: str) -> List[Collection]:
        """Get child collections."""
        return [c for c in self._collections.values() if c.parent_id == collection_id]

    def add_document(
        self,
        collection_id: str,
        document_id: str
    ) -> bool:
        """
        Add a document to a collection.

        Args:
            collection_id: Collection to add to
            document_id: Document to add

        Returns:
            True if added successfully
        """
        if collection := self._collections.get(collection_id):
            if collection.is_smart:
                logger.warning("Cannot manually add to smart collection")
                return False

            if document_id not in collection.document_ids:
                collection.document_ids.append(document_id)
                collection.updated_at = datetime.now().isoformat()

                # Update reverse index
                if document_id not in self._doc_to_collections:
                    self._doc_to_collections[document_id] = set()
                self._doc_to_collections[document_id].add(collection_id)

                self._save_state()
                return True

        return False

    def remove_document(
        self,
        collection_id: str,
        document_id: str
    ) -> bool:
        """
        Remove a document from a collection.

        Args:
            collection_id: Collection to remove from
            document_id: Document to remove

        Returns:
            True if removed successfully
        """
        if collection := self._collections.get(collection_id):
            if document_id in collection.document_ids:
                collection.document_ids.remove(document_id)
                collection.updated_at = datetime.now().isoformat()

                # Update reverse index
                if document_id in self._doc_to_collections:
                    self._doc_to_collections[document_id].discard(collection_id)

                self._save_state()
                return True

        return False

    def get_document_collections(self, document_id: str) -> List[Collection]:
        """Get all collections containing a document."""
        collection_ids = self._doc_to_collections.get(document_id, set())
        return [self._collections[cid] for cid in collection_ids if cid in self._collections]

    def update_collection(
        self,
        collection_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        icon: Optional[str] = None
    ) -> bool:
        """Update collection metadata."""
        if collection := self._collections.get(collection_id):
            if name is not None:
                collection.name = name
            if description is not None:
                collection.description = description
            if color is not None:
                collection.color = color
            if icon is not None:
                collection.icon = icon

            collection.updated_at = datetime.now().isoformat()
            self._save_state()
            return True

        return False

    def delete_collection(
        self,
        collection_id: str,
        recursive: bool = False
    ) -> bool:
        """
        Delete a collection.

        Args:
            collection_id: Collection to delete
            recursive: Also delete child collections

        Returns:
            True if deleted successfully
        """
        if collection_id not in self._collections:
            return False

        # Handle children
        children = self.get_children(collection_id)
        if children and not recursive:
            logger.warning("Collection has children, use recursive=True to delete")
            return False

        if recursive:
            for child in children:
                self.delete_collection(child.collection_id, recursive=True)

        # Remove from reverse index
        collection = self._collections[collection_id]
        for doc_id in collection.document_ids:
            if doc_id in self._doc_to_collections:
                self._doc_to_collections[doc_id].discard(collection_id)

        del self._collections[collection_id]
        self._save_state()

        logger.info(f"Deleted collection: {collection_id}")

        return True

    def move_collection(
        self,
        collection_id: str,
        new_parent_id: Optional[str]
    ) -> bool:
        """Move a collection to a new parent."""
        if collection := self._collections.get(collection_id):
            # Prevent circular references
            if new_parent_id:
                parent = new_parent_id
                while parent:
                    if parent == collection_id:
                        logger.error("Cannot create circular reference")
                        return False
                    parent_collection = self._collections.get(parent)
                    parent = parent_collection.parent_id if parent_collection else None

            collection.parent_id = new_parent_id
            collection.updated_at = datetime.now().isoformat()
            self._save_state()
            return True

        return False

    def refresh_smart_collection(
        self,
        collection_id: str,
        search_func
    ) -> int:
        """
        Refresh a smart collection by running its query.

        Args:
            collection_id: Smart collection to refresh
            search_func: Function to run search (query, filters) -> results

        Returns:
            Number of documents in refreshed collection
        """
        collection = self._collections.get(collection_id)

        if not collection or not collection.is_smart:
            return 0

        # Run search
        results = search_func(
            collection.smart_query,
            collection.smart_filters
        )

        # Update document list
        old_docs = set(collection.document_ids)
        new_docs = {r.get("id") for r in results if r.get("id")}

        collection.document_ids = list(new_docs)
        collection.updated_at = datetime.now().isoformat()

        # Update reverse index
        for doc_id in old_docs - new_docs:
            if doc_id in self._doc_to_collections:
                self._doc_to_collections[doc_id].discard(collection_id)

        for doc_id in new_docs:
            if doc_id not in self._doc_to_collections:
                self._doc_to_collections[doc_id] = set()
            self._doc_to_collections[doc_id].add(collection_id)

        self._save_state()

        return len(collection.document_ids)

    def get_collection_tree(self) -> List[Dict]:
        """Get hierarchical collection structure."""
        def build_tree(parent_id: Optional[str]) -> List[Dict]:
            children = self.get_children(parent_id) if parent_id else self.get_root_collections()

            return [
                {
                    "id": c.collection_id,
                    "name": c.name,
                    "icon": c.icon,
                    "color": c.color,
                    "document_count": len(c.document_ids),
                    "is_smart": c.is_smart,
                    "children": build_tree(c.collection_id)
                }
                for c in children
            ]

        return build_tree(None)

    def _load_state(self) -> None:
        """Load state from disk."""
        state_file = self.state_dir / "collections.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)

                for cid, cdata in data.get("collections", {}).items():
                    self._collections[cid] = Collection(**cdata)

                    # Rebuild reverse index
                    for doc_id in cdata.get("document_ids", []):
                        if doc_id not in self._doc_to_collections:
                            self._doc_to_collections[doc_id] = set()
                        self._doc_to_collections[doc_id].add(cid)

            except Exception as e:
                logger.error(f"Failed to load collections: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.state_dir / "collections.json"

        data = {
            "collections": {
                cid: {
                    "collection_id": c.collection_id,
                    "name": c.name,
                    "description": c.description,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                    "document_ids": c.document_ids,
                    "color": c.color,
                    "icon": c.icon,
                    "parent_id": c.parent_id,
                    "is_smart": c.is_smart,
                    "smart_query": c.smart_query,
                    "smart_filters": c.smart_filters
                }
                for cid, c in self._collections.items()
            },
            "updated_at": datetime.now().isoformat()
        }

        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)
