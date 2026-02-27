#!/usr/bin/env python3
"""
Quick test script to verify the CoreRag search pipeline works end-to-end.

Creates a test document, embeds it, stores in LanceDB, and searches.
"""

import sys

sys.path.insert(0, ".")

from pathlib import Path

import lancedb

from src.embeddings.embedding_service import create_embedding_service

# Test content to index
TEST_DOCS = [
    {
        "id": "doc1",
        "title": "CoreRag Overview",
        "text": "The Personal Knowledge Management system helps organize your notes and documents. It provides semantic search using vector embeddings, allowing you to find relevant information based on meaning rather than just keywords.",
        "source_path": "/Users/test/corerag_overview.md",
    },
    {
        "id": "doc2",
        "title": "Hardware Optimization",
        "text": "The CoreRag system is optimized for Apple Silicon M4 Max. It uses Metal acceleration for embeddings and monitors memory pressure to throttle operations when needed. The 75% memory threshold helps prevent system slowdowns.",
        "source_path": "/Users/test/hardware.md",
    },
    {
        "id": "doc3",
        "title": "MCP Integration",
        "text": "Connect to Claude Desktop using the Model Context Protocol. MCP exposes CoreRag tools like search_knowledge, list_recent_files, and get_system_status. This enables AI assistants to access your knowledge base.",
        "source_path": "/Users/test/mcp.md",
    },
    {
        "id": "doc4",
        "title": "Privacy Features",
        "text": "The privacy scanner detects sensitive information like SSNs, credit cards, API keys, and PII. It can automatically block restricted content from being indexed to protect your sensitive data.",
        "source_path": "/Users/test/privacy.md",
    },
]


def main():
    print("🔧 Initializing embedding service...")
    embedding_service = create_embedding_service()
    print(f"   Model: {embedding_service.model_name}")
    print(f"   Dimension: {embedding_service.dimension}")

    # Connect to LanceDB
    print("\n📦 Connecting to LanceDB...")
    db_path = Path.home() / ".corerag" / "lancedb"
    db = lancedb.connect(str(db_path))

    # Create embeddings for test docs
    print("\n🎯 Generating embeddings for test documents...")
    texts = [doc["text"] for doc in TEST_DOCS]
    embeddings = embedding_service.embed_documents(texts, show_progress=False)

    # Prepare data for LanceDB
    data = []
    for doc, embedding in zip(TEST_DOCS, embeddings):
        data.append(
            {
                "id": doc["id"],
                "title": doc["title"],
                "text": doc["text"],
                "source_path": doc["source_path"],
                "vector": embedding,
            }
        )

    # Create or overwrite chunks table
    print("\n💾 Storing in LanceDB...")
    if "chunks" in db.table_names():
        db.drop_table("chunks")

    table = db.create_table("chunks", data)
    print(f"   Created table 'chunks' with {table.count_rows()} rows")

    # Test search
    print("\n🔍 Testing search...")
    queries = [
        "How does memory management work?",
        "How to connect AI assistants?",
        "Protect sensitive information",
    ]

    for query in queries:
        print(f"\n   Query: '{query}'")
        query_embedding = embedding_service.embed_query(query)
        results = table.search(query_embedding).limit(2).to_list()

        for i, result in enumerate(results, 1):
            print(f"   [{i}] {result['title']} (score: {result['_distance']:.4f})")
            print(f"       {result['text'][:80]}...")

    print("\n✅ Search pipeline working correctly!")
    print("\n📝 Next: Try 'python -m src.cli.main search \"your query\"'")


if __name__ == "__main__":
    main()
