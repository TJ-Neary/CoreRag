# Architecture Documentation

Design documents for CoreRag's subsystems and integration patterns.

## Core System

| Document | Description |
|----------|-------------|
| [System Architecture](CoreRag_Design_System_Architecture.md) | Complete system overview — ingestion pipeline, search stack, dashboard, and MCP server |
| [Data Schema](data_schema.md) | Document, Chunk, and SearchResult models with LanceDB table definitions |
| [MCP Server](CoreRag_Design_MCP_Server.md) | FastMCP stdio transport, tool definitions, and Claude Desktop integration |
| [Metadata Schema](CoreRag_Design_Metadata_Schema.md) | Metadata fields, PII annotations, and staging manifest format |

## Search & Retrieval

| Document | Description |
|----------|-------------|
| [Chunking Strategy](CHUNKING_STRATEGY.md) | Parent-child hierarchical chunking (2048/512 tokens) with section-aware splitting |
| [Multimodal Search](MULTIMODAL_SEARCH.md) | Cross-modal search across text, images, audio, and video |
| [Search UX](SEARCH_UX.md) | Search interface specifications and result presentation |
| [Migration Strategy](MIGRATION_STRATEGY.md) | Embedding model migration with zero-downtime re-indexing |

## Infrastructure & Safety

| Document | Description |
|----------|-------------|
| [Hardware Safety](HARDWARE_SAFETY.md) | RAM/CPU/temperature monitoring, throttle controller, and emergency shutdown |
| [Performance Guide](PERFORMANCE_GUIDE.md) | Optimization for M4 Max — batch sizes, MPS acceleration, LanceDB tuning |
| [Resilience](RESILIENCE.md) | Recovery architecture — checkpoints, backup/restore, corruption repair |
| [Deployment Options](CoreRag_Design_Deployment_Options.md) | Performance tiers from M1 to M4 Max with resource allocation |

## Privacy & Access

| Document | Description |
|----------|-------------|
| [Access Control](ACCESS_CONTROL.md) | API key auth, privacy tiers (public/private/sensitive), and PII redaction flow |
| [Personal Context](CoreRag_Design_Personal_Context.md) | Episodic memory, user profiles, and correction learning |

## Quality & Operations

| Document | Description |
|----------|-------------|
| [Testing Framework](TESTING_FRAMEWORK.md) | Test strategy, fixture patterns, mutation testing with mutmut |
| [Obsidian Sync](OBSIDIAN_SYNC.md) | Markdown export, backlink generation, and vault conflict resolution |
