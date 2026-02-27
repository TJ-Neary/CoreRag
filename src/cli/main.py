#!/usr/bin/env python3
"""
CoreRag Command-Line Interface.

A comprehensive CLI for manual CoreRag operations:
- Search and query
- File ingestion
- System status
- Maintenance tasks
- Configuration
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.exceptions import CoreRagError
from src.utils.logging_config import setup_logging
from src.utils.path_validation import PathValidationError, validate_path

# Configure logging (centralized: colored console, rotating file, JSON, error-only)
logger = setup_logging()


class Colors:
    """ANSI color codes for terminal output."""

    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def color(text: str, c: str) -> str:
    """Apply color to text."""
    return f"{c}{text}{Colors.ENDC}"


def print_header(text: str) -> None:
    """Print a header."""
    print(f"\n{color(text, Colors.BOLD + Colors.HEADER)}")
    print("=" * len(text))


def print_success(text: str) -> None:
    """Print success message."""
    print(color(f"✓ {text}", Colors.GREEN))


def print_error(text: str) -> None:
    """Print error message."""
    print(color(f"✗ {text}", Colors.RED))


def print_warning(text: str) -> None:
    """Print warning message."""
    print(color(f"⚠ {text}", Colors.YELLOW))


def print_info(text: str) -> None:
    """Print info message."""
    print(color(f"ℹ {text}", Colors.CYAN))


# === Search Command ===


def cmd_search(args: argparse.Namespace) -> int:
    """Execute search query."""
    try:
        from src.embeddings.embedding_service import create_embedding_service

        print_header(f"Searching: {args.query}")

        # Initialize services
        embedding_service = create_embedding_service()

        # Simple embedding search (without full infrastructure)
        query_embedding = embedding_service.embed_query(args.query)

        # Connect to LanceDB
        import lancedb

        from src.config import DB_PATH

        db_path = args.db_path or DB_PATH
        db = lancedb.connect(str(db_path))

        if "child_chunks" not in db.table_names():
            print_warning("No child_chunks table found. Have you ingested any files?")
            return 1

        table = db.open_table("child_chunks")
        results = table.search(query_embedding).limit(args.limit).to_list()

        if not results:
            print_warning("No results found.")
            return 0

        print(f"\nFound {len(results)} results:\n")

        for i, result in enumerate(results, 1):
            score = result.get("_distance", 0)
            source = Path(result.get("source_path", "Unknown")).name
            content = result.get("content", result.get("text", ""))[:200]

            print(f"{color(f'[{i}]', Colors.BOLD)} {source}")
            print(f"    Score: {score:.4f}")
            print(f"    {color(content, Colors.DIM)}...")
            print()

        return 0

    except CoreRagError as e:
        print_error(f"Search failed: {e}")
        logger.error(f"Search error: {e}")
        return 1
    except Exception as e:
        print_error(f"Search failed: {e}")
        logger.exception("Search error")
        return 1


# === Ingest Command ===


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest files or directories into CoreRag via the processing pipeline."""
    try:
        from src.processor import process_document

        # Validate and canonicalize the path
        try:
            target = validate_path(args.path, must_exist=True, allow_outside_configured=True)
        except PathValidationError as e:
            print_error(f"Invalid path: {e}")
            return 1

        print_header(f"Ingesting: {target}")
        if args.tags:
            print_info(f"Tags: {', '.join(args.tags)}")

        # Collect files to process
        files: list[Path] = []
        if target.is_file():
            files = [target]
        else:
            pattern = "**/*" if args.recursive else "*"
            files = sorted(
                f for f in target.glob(pattern) if f.is_file() and not f.name.startswith(".")
            )

        if not files:
            print_warning("No files found to ingest.")
            return 0

        print_info(f"Found {len(files)} file(s) to process")

        # Process each file through the pipeline
        success_count = 0
        fail_count = 0
        for i, file_path in enumerate(files, 1):
            print_info(f"[{i}/{len(files)}] Processing: {file_path.name}")
            try:
                tags = args.tags if args.tags else None
                result = process_document(file_path, tags=tags)
                if result:
                    print_success(f"  Staged: {file_path.name}")
                    success_count += 1
                else:
                    print_warning(f"  Skipped: {file_path.name}")
                    fail_count += 1
            except Exception as e:
                print_error(f"  Failed: {file_path.name} — {e}")
                fail_count += 1

        print()
        print_success(f"Completed: {success_count} file(s) staged for review")
        if fail_count > 0:
            print_warning(f"Failed/Skipped: {fail_count} file(s)")
        print_info("Use the dashboard to review and approve staged files.")

        return 0

    except CoreRagError as e:
        print_error(f"Ingestion failed: {e}")
        logger.error(f"Ingestion error: {e}")
        return 1
    except Exception as e:
        print_error(f"Ingestion failed: {e}")
        logger.exception("Ingestion error")
        return 1


# === Status Command ===


def cmd_status(args: argparse.Namespace) -> int:
    """Show system status."""
    try:
        import psutil

        print_header("CoreRag Status")

        # Memory
        memory = psutil.virtual_memory()
        mem_percent = memory.percent
        mem_color = (
            Colors.GREEN if mem_percent < 60 else Colors.YELLOW if mem_percent < 80 else Colors.RED
        )
        print(
            f"\nMemory: {color(f'{mem_percent:.1f}%', mem_color)} used "
            f"({memory.used / (1024**3):.1f}GB / {memory.total / (1024**3):.1f}GB)"
        )

        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_color = (
            Colors.GREEN if cpu_percent < 50 else Colors.YELLOW if cpu_percent < 80 else Colors.RED
        )
        print(f"CPU: {color(f'{cpu_percent:.1f}%', cpu_color)} used")

        # Database
        from src.config import DB_PATH, STATE_DIR

        db_path = DB_PATH
        if db_path.exists():
            import lancedb

            db = lancedb.connect(str(db_path))
            tables = db.table_names()
            print(f"\nDatabase: {color('Connected', Colors.GREEN)}")
            print(f"  Tables: {', '.join(tables) if tables else 'None'}")

            if "child_chunks" in tables:
                table = db.open_table("child_chunks")
                count = table.count_rows()
                print(f"  Child chunks indexed: {count:,}")
        else:
            print(f"\nDatabase: {color('Not initialized', Colors.YELLOW)}")

        # State directory
        state_dir = STATE_DIR
        if state_dir.exists():
            total_size = sum(f.stat().st_size for f in state_dir.rglob("*") if f.is_file())
            print(f"\nState directory: {total_size / (1024**2):.1f} MB")

        return 0

    except CoreRagError as e:
        print_error(f"Status check failed: {e}")
        return 1
    except Exception as e:
        print_error(f"Status check failed: {e}")
        return 1


# === Check Links Command ===


def cmd_check_links(args: argparse.Namespace) -> int:
    """Check for broken links."""
    try:
        from src.quality.link_checker import LinkChecker, format_report

        # Validate and canonicalize the path
        try:
            target = validate_path(args.path, must_exist=True, allow_outside_configured=True)
        except PathValidationError as e:
            print_error(f"Invalid path: {e}")
            return 1

        print_header(f"Checking links in: {target}")

        checker = LinkChecker()

        # Run async check
        report = asyncio.run(
            checker.scan_directory(
                target,
                recursive=args.recursive,
            )
        )

        # Print summary
        print(f"\nScanned {report.documents_scanned} documents")
        print(f"Found {report.total_links} total links ({report.unique_links} unique)")

        health_color = (
            Colors.GREEN
            if report.overall_health > 90
            else Colors.YELLOW if report.overall_health > 70 else Colors.RED
        )
        print(f"Health: {color(f'{report.overall_health:.1f}%', health_color)}")

        if report.broken_links > 0:
            print(f"\n{color(f'Broken links: {report.broken_links}', Colors.RED)}")

            for file_path, url, result in report.broken_details[:10]:
                print(f"  - {Path(file_path).name}: {url}")
                print(f"    {result.status.value}: {result.error_message or 'N/A'}")

            if len(report.broken_details) > 10:
                print(f"  ... and {len(report.broken_details) - 10} more")

        # Save report if requested
        if args.output:
            report_text = format_report(report)
            Path(args.output).write_text(report_text)
            print_success(f"Report saved to: {args.output}")

        return 0

    except CoreRagError as e:
        print_error(f"Link check failed: {e}")
        logger.error(f"Link check error: {e}")
        return 1
    except Exception as e:
        print_error(f"Link check failed: {e}")
        logger.exception("Link check error")
        return 1


# === Find Duplicates Command ===


def cmd_duplicates(args: argparse.Namespace) -> int:
    """Find duplicate content."""
    try:
        from src.quality.duplicate_detector import DuplicateDetector

        # Validate and canonicalize the path
        try:
            target = validate_path(args.path, must_exist=True, allow_outside_configured=True)
        except PathValidationError as e:
            print_error(f"Invalid path: {e}")
            return 1

        print_header(f"Finding duplicates in: {target}")

        detector = DuplicateDetector()
        report = detector.scan_directory(
            target,
            recursive=args.recursive,
        )

        total_dupes = report.exact_duplicates + report.near_duplicates + report.semantic_duplicates
        print(f"\nScanned {report.total_files} files")
        print(
            f"Found {total_dupes} duplicates "
            f"(exact: {report.exact_duplicates}, near: {report.near_duplicates}, "
            f"semantic: {report.semantic_duplicates})"
        )
        print(f"Potential savings: {report.space_reclaimable_bytes / (1024 * 1024):.1f} MB")

        if report.matches:
            print("\nDuplicate pairs:")
            for i, match in enumerate(report.matches[:10], 1):
                print(f"\n{color(f'Pair {i}:', Colors.BOLD)}")
                print(f"  File 1: {Path(match.file1).name}")
                print(f"  File 2: {Path(match.file2).name}")
                print(f"    Similarity: {match.similarity:.1%} ({match.match_type})")

        return 0

    except CoreRagError as e:
        print_error(f"Duplicate check failed: {e}")
        logger.error(f"Duplicate check error: {e}")
        return 1
    except Exception as e:
        print_error(f"Duplicate check failed: {e}")
        logger.exception("Duplicate check error")
        return 1


# === Find Stale Command ===


def cmd_stale(args: argparse.Namespace) -> int:
    """Find stale content."""
    try:
        from src.quality.freshness import FreshnessIndicator

        # Validate and canonicalize the path
        try:
            target = validate_path(args.path, must_exist=True, allow_outside_configured=True)
        except PathValidationError as e:
            print_error(f"Invalid path: {e}")
            return 1

        print_header(f"Finding stale content in: {target}")

        indicator = FreshnessIndicator(stale_days=args.days)
        stale = indicator.get_stale_content(target, recursive=args.recursive)

        if not stale:
            print_success("No stale content found!")
            return 0

        print(f"\nFound {len(stale)} stale files (>{args.days} days old):\n")

        for item in stale[:20]:
            age_color = Colors.YELLOW if item.age_days < 365 else Colors.RED
            print(f"  {Path(item.file_path).name}")
            print(f"    Age: {color(f'{item.age_days} days', age_color)}")
            print(f"    Last modified: {item.modified_at.strftime('%Y-%m-%d')}")

        if len(stale) > 20:
            print(f"\n  ... and {len(stale) - 20} more")

        # Summary
        summary = indicator.get_freshness_summary(target)
        print("\nSummary:")
        print(f"  Total files: {summary['total_files']}")
        print(f"  Average age: {summary['avg_age_days']:.0f} days")
        print(f"  Fresh (<7 days): {summary['fresh_percentage']:.1f}%")

        return 0

    except CoreRagError as e:
        print_error(f"Stale check failed: {e}")
        logger.error(f"Stale check error: {e}")
        return 1
    except Exception as e:
        print_error(f"Stale check failed: {e}")
        logger.exception("Stale check error")
        return 1


# === Tag Command ===


def cmd_tag(args: argparse.Namespace) -> int:
    """Auto-tag files."""
    try:
        from src.classification.auto_tagger import AutoTagger

        # Validate and canonicalize the path
        try:
            target = validate_path(args.path, must_exist=True, allow_outside_configured=True)
        except PathValidationError as e:
            print_error(f"Invalid path: {e}")
            return 1

        print_header(f"Auto-tagging: {target}")

        tagger = AutoTagger()

        if target.is_file():
            result = tagger.tag_file(target)
            print(f"\nFile: {target.name}")
            print(f"Tags: {', '.join(result.assigned_tags) or 'None'}")
            if result.suggested_tags:
                print(f"Suggested: {', '.join(result.suggested_tags)}")
        else:
            results = tagger.tag_directory(target, recursive=args.recursive)
            tagged_count = sum(1 for r in results.values() if r.assigned_tags)
            print(f"\nTagged {tagged_count} of {len(results)} files")

            # Show distribution
            all_tags: dict[str, int] = {}
            for result in results.values():
                for tag in result.assigned_tags:
                    all_tags[tag] = all_tags.get(tag, 0) + 1

            if all_tags:
                print("\nTag distribution:")
                for tag, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]:
                    print(f"  {tag}: {count}")

        return 0

    except CoreRagError as e:
        print_error(f"Tagging failed: {e}")
        logger.error(f"Tagging error: {e}")
        return 1
    except Exception as e:
        print_error(f"Tagging failed: {e}")
        logger.exception("Tagging error")
        return 1


# === PII Dictionary Command ===


def cmd_pii(args: argparse.Namespace) -> int:
    """Manage custom PII dictionary."""
    import yaml

    from src.config import STATE_DIR
    from src.utils.secure_file import secure_write

    pii_path = STATE_DIR / "pii_terms.yaml"

    if not args.pii_action:
        print_error("Usage: corerag pii {list|add|remove}")
        return 1

    if args.pii_action == "list":
        if not pii_path.exists():
            print_info("No custom PII terms defined.")
            print_info(f"File location: {pii_path}")
            print_info("Add terms with: corerag pii add <term> --type TYPE")
            return 0

        with open(pii_path) as f:
            data = yaml.safe_load(f) or {}

        terms = data.get("terms", [])
        if not terms:
            print_info("No custom PII terms defined.")
            return 0

        print_header(f"Custom PII Terms ({len(terms)})")
        for t in terms:
            term_type = t.get("type", "CUSTOM")
            value = t.get("value", "")
            print(f"  [{color(term_type, Colors.CYAN)}] {value}")
        return 0

    elif args.pii_action == "add":
        data = {"terms": []}
        if pii_path.exists():
            with open(pii_path) as f:
                data = yaml.safe_load(f) or {"terms": []}
        if not isinstance(data.get("terms"), list):
            data["terms"] = []

        # Check for duplicates
        existing = {t.get("value", "").lower() for t in data["terms"]}
        if args.term.lower() in existing:
            print_warning(f"Term already exists: {args.term}")
            return 1

        data["terms"].append({"value": args.term, "type": args.type.upper()})

        # Write with secure permissions (owner-only access to PII data)
        content = yaml.dump(data, default_flow_style=False)
        secure_write(pii_path, content)

        print_success(f"Added PII term: [{args.type.upper()}] {args.term}")
        print_info(f"Saved to {pii_path} (permissions: 0600)")
        return 0

    elif args.pii_action == "remove":
        if not pii_path.exists():
            print_error("No PII terms file found.")
            return 1

        with open(pii_path) as f:
            data = yaml.safe_load(f) or {"terms": []}

        original_count = len(data.get("terms", []))
        data["terms"] = [
            t for t in data.get("terms", []) if t.get("value", "").lower() != args.term.lower()
        ]

        if len(data["terms"]) == original_count:
            print_warning(f"Term not found: {args.term}")
            return 1

        # Write with secure permissions
        content = yaml.dump(data, default_flow_style=False)
        secure_write(pii_path, content)

        print_success(f"Removed PII term: {args.term}")
        return 0

    else:
        print_error("Usage: corerag pii {list|add|remove}")
        return 1


# === Health Command ===


def cmd_health(args: argparse.Namespace) -> int:
    """Run system health checks."""
    try:
        # Database-only mode uses the unified health checker
        if args.db:
            from src.maintenance.health_check import HealthChecker as DBHealthChecker

            print_header("CoreRag Database Health")

            checker = DBHealthChecker()
            report = checker.full_report() if args.full else checker.quick_check()

            status_colors = {
                "healthy": Colors.GREEN,
                "degraded": Colors.YELLOW,
                "critical": Colors.RED,
            }
            c = status_colors.get(report.status, Colors.DIM)
            print(f"\nStatus: {color(report.status.upper(), c)}")
            print(f"Database: {report.db_path}")

            if report.total_size_mb > 0:
                print(f"Total size: {report.total_size_mb:.1f} MB")

            if report.tables:
                print("\nTables:")
                for t in report.tables:
                    parts = [f"{t.rows} rows"]
                    if t.size_mb > 0:
                        parts.append(f"{t.size_mb:.1f} MB")
                    if t.fragmentation > 0:
                        parts.append(f"{t.fragmentation:.0%} fragmentation")
                    print(f"  {color(t.name, Colors.BOLD)}: {', '.join(parts)}")

            for error in report.errors:
                print(f"\n  {color('ERROR', Colors.RED)}: {error}")
            for warning in report.warnings:
                print(f"\n  {color('WARN', Colors.YELLOW)}: {warning}")
            for rec in report.recommendations:
                print(f"\n  {color('REC', Colors.BLUE)}: {rec}")

            return 0

        # Full system health check
        from src.utils.health import HealthChecker

        print_header("CoreRag Health Check")

        checker = HealthChecker()
        status = checker.run_all_checks()

        status_colors = {
            "healthy": Colors.GREEN,
            "degraded": Colors.YELLOW,
            "unhealthy": Colors.RED,
            "unknown": Colors.DIM,
        }

        overall = status.status.value.lower()
        print(f"\nOverall: {color(overall.upper(), status_colors.get(overall, Colors.DIM))}")
        print(f"Uptime: {status.uptime_seconds:.0f}s")

        for check in status.checks:
            c = status_colors.get(check.status.value.lower(), Colors.DIM)
            print(f"\n  {color(check.name, Colors.BOLD)}: {color(check.status.value, c)}")
            print(f"    {check.message}")
            if check.latency_ms > 0:
                print(f"    Latency: {check.latency_ms:.0f}ms")
            if args.verbose and check.details:
                for k, v in check.details.items():
                    print(f"    {k}: {v}")

        return 0

    except CoreRagError as e:
        print_error(f"Health check failed: {e}")
        logger.error(f"Health check error: {e}")
        return 1
    except Exception as e:
        print_error(f"Health check failed: {e}")
        logger.exception("Health check error")
        return 1


# === Optimize Database Command ===


def cmd_optimize_db(args: argparse.Namespace) -> int:
    """Optimize LanceDB database."""
    try:
        from src.maintenance.db_optimizer import LanceDBOptimizer

        print_header("Database Optimization")

        optimizer = LanceDBOptimizer()

        if args.report_only:
            report = optimizer.get_health_report()
            print(f"\nDatabase: {report.db_path}")
            print(f"Total size: {report.total_size_mb:.1f} MB")
            print(f"Fragmentation: {report.fragmentation_estimate:.0%}")

            if report.tables:
                print("\nTables:")
                for t in report.tables:
                    print(
                        f"  {color(t['name'], Colors.BOLD)}: "
                        f"{t['rows']} rows, {t['size_mb']:.1f} MB"
                    )

            if report.recommendations:
                print("\nRecommendations:")
                for rec in report.recommendations:
                    print(f"  - {rec}")
            return 0

        print_info("Running optimization (this may create a backup first)...")
        results = optimizer.optimize_all()

        for r in results:
            if r.success:
                print_success(
                    f"{r.table_name}: {r.original_size_mb:.1f} MB -> "
                    f"{r.optimized_size_mb:.1f} MB "
                    f"(saved {r.space_saved_mb:.1f} MB in {r.duration_seconds:.1f}s)"
                )
            else:
                print_error(f"{r.table_name}: {r.error}")

        total_saved = sum(r.space_saved_mb for r in results if r.success)
        if total_saved > 0:
            print(f"\nTotal space saved: {total_saved:.1f} MB")

        return 0

    except CoreRagError as e:
        print_error(f"Optimization failed: {e}")
        logger.error(f"Optimization error: {e}")
        return 1
    except Exception as e:
        print_error(f"Optimization failed: {e}")
        logger.exception("Optimization error")
        return 1


# === Backup Command ===


def cmd_backup(args: argparse.Namespace) -> int:
    """Manage backups."""
    try:
        from src.config import STATE_DIR
        from src.utils.backup import BackupManager

        manager = BackupManager(data_dir=STATE_DIR)

        if args.backup_action == "create":
            print_header("Creating Backup")
            info = manager.create_backup(
                backup_name=args.name,
                backup_type=args.type,
            )
            print_success(f"Backup created: {info.name}")
            print(f"  Size: {info.size_bytes / (1024 * 1024):.1f} MB")
            print(f"  Path: {info.path}")
            return 0

        elif args.backup_action == "list":
            backups = manager.list_backups()
            if not backups:
                print_info("No backups found.")
                return 0

            print_header(f"Backups ({len(backups)})")
            for b in backups:
                size_mb = b.size_bytes / (1024 * 1024)
                print(f"\n  {color(b.name, Colors.BOLD)}")
                print(f"    Type: {b.backup_type} | Size: {size_mb:.1f} MB")
                print(f"    Created: {b.timestamp}")
            return 0

        elif args.backup_action == "restore":
            if not args.name:
                print_error("Backup name required: corerag backup restore <name>")
                return 1

            print_header(f"Restoring Backup: {args.name}")
            print_warning("This will overwrite current data!")

            success = manager.restore_backup(args.name)
            if success:
                print_success("Backup restored successfully.")
            else:
                print_error("Restore failed.")
            return 0 if success else 1

        elif args.backup_action == "cleanup":
            removed = manager.cleanup_old_backups(keep_count=args.keep)
            print_success(f"Removed {removed} old backup(s).")
            return 0

        else:
            print_error("Usage: corerag backup {create|list|restore|cleanup}")
            return 1

    except CoreRagError as e:
        print_error(f"Backup operation failed: {e}")
        logger.error(f"Backup error: {e}")
        return 1
    except Exception as e:
        print_error(f"Backup operation failed: {e}")
        logger.exception("Backup error")
        return 1


# === Knowledge Graph Command ===


def cmd_graph(args: argparse.Namespace) -> int:
    """Query the knowledge graph."""
    try:
        from src.config import DB_PATH
        from src.graph.knowledge_graph import KnowledgeGraph

        graph_db_path = DB_PATH.parent / "knowledge_graph.db"
        if not graph_db_path.exists():
            print_warning("Knowledge graph not initialized. Ingest documents first.")
            return 1

        graph = KnowledgeGraph(graph_db_path)

        if args.graph_action == "stats":
            stats = graph.get_stats()
            print_header("Knowledge Graph Statistics")
            print(f"\n  Entities: {stats['total_entities']}")
            print(f"  Relationships: {stats['total_relationships']}")

            if stats.get("entity_types"):
                print("\n  Entity types:")
                for etype, count in sorted(
                    stats["entity_types"].items(), key=lambda x: x[1], reverse=True
                ):
                    print(f"    {etype}: {count}")

            if stats.get("relationship_types"):
                print("\n  Relationship types:")
                for rtype, count in sorted(
                    stats["relationship_types"].items(), key=lambda x: x[1], reverse=True
                )[:15]:
                    print(f"    {rtype}: {count}")
            return 0

        elif args.graph_action == "query":
            if not args.entity:
                print_error("Entity name required: corerag graph query <entity>")
                return 1

            print_header(f"Graph: {args.entity}")
            neighbors = graph.get_neighbors(args.entity)

            if not neighbors:
                print_warning(f"No connections found for '{args.entity}'.")
                return 0

            print(f"\nFound {len(neighbors)} connection(s):\n")
            for n in neighbors[:20]:
                direction = n.get("direction", "")
                rel = n.get("relationship", "")
                entity = n.get("entity", "")
                arrow = "->" if direction == "outgoing" else "<-"
                print(f"  {args.entity} {arrow} [{rel}] {arrow} {entity}")

            if len(neighbors) > 20:
                print(f"\n  ... and {len(neighbors) - 20} more")
            return 0

        elif args.graph_action == "path":
            if not args.entity or not args.target:
                print_error("Usage: corerag graph path <start> <end>")
                return 1

            path = graph.find_path(args.entity, args.target, max_hops=args.hops)
            if path is None:
                print_warning(
                    f"No path found between '{args.entity}' and '{args.target}' "
                    f"(max {args.hops} hops)."
                )
                return 0

            print_header(f"Path: {args.entity} -> {args.target}")
            for triple in path:
                print(f"  {triple.subject} --[{triple.predicate}]--> {triple.object}")
            return 0

        else:
            print_error("Usage: corerag graph {stats|query|path}")
            return 1

    except CoreRagError as e:
        print_error(f"Graph query failed: {e}")
        logger.error(f"Graph error: {e}")
        return 1
    except Exception as e:
        print_error(f"Graph query failed: {e}")
        logger.exception("Graph error")
        return 1


# === Memory Command ===


def cmd_memory(args: argparse.Namespace) -> int:
    """Manage episodic memory (user facts)."""
    try:
        from src.config import STATE_DIR
        from src.memory.episodic_memory import EpisodicMemoryManager

        manager = EpisodicMemoryManager(storage_path=STATE_DIR / "memory")
        user_id = args.user or "default"

        if args.memory_action == "list":
            profile = manager.load_or_create(user_id)

            if not profile.facts:
                print_info(f"No facts stored for user '{user_id}'.")
                return 0

            print_header(f"User Facts: {user_id} ({len(profile.facts)} facts)")
            for i, fact in enumerate(profile.facts, 1):
                cat = fact.category.value if hasattr(fact.category, "value") else str(fact.category)
                print(f"\n  {color(f'[{i}]', Colors.BOLD)} [{cat}] {fact.content}")
                print(f"      Confidence: {fact.confidence:.0%} | Source: {fact.source}")
                print(f"      Created: {fact.created_at}")
                if fact.expires_at:
                    print(f"      Expires: {fact.expires_at}")
            return 0

        elif args.memory_action == "add":
            if not args.fact:
                print_error('Fact content required: corerag memory add "fact text"')
                return 1

            from src.memory.episodic_memory import FactCategory, UserFact

            profile = manager.load_or_create(user_id)

            # Map category string to enum
            cat_map = {c.value.lower(): c for c in FactCategory}
            category = cat_map.get(args.category.lower(), FactCategory.PERSONAL)

            fact = UserFact(
                content=args.fact,
                category=category,
                confidence=1.0,
                source="cli",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                expires_at=None,
                context=None,
            )
            manager.add_fact(profile, fact)
            manager.save(profile)

            print_success(f"Added fact for '{user_id}': {args.fact}")
            return 0

        elif args.memory_action == "context":
            profile = manager.load_or_create(user_id)
            context = manager.get_context_injection(profile)

            if not context.strip():
                print_info(f"No context available for user '{user_id}'.")
                return 0

            print_header(f"Context Injection: {user_id}")
            print(context)
            return 0

        elif args.memory_action == "export":
            profile = manager.load_or_create(user_id)
            output = manager.get_as_json(profile)
            print(output)
            return 0

        else:
            print_error("Usage: corerag memory {list|add|context|export}")
            return 1

    except CoreRagError as e:
        print_error(f"Memory operation failed: {e}")
        logger.error(f"Memory error: {e}")
        return 1
    except Exception as e:
        print_error(f"Memory operation failed: {e}")
        logger.exception("Memory error")
        return 1


# === Main ===


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="corerag",
        description="Personal Knowledge Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search your knowledge base")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Max results")
    search_parser.add_argument("--hyde", action="store_true", help="Use HyDE expansion")
    search_parser.add_argument("--db-path", type=Path, help="Database path")
    search_parser.set_defaults(func=cmd_search)

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest files or directories")
    ingest_parser.add_argument("path", type=Path, help="File or directory to ingest")
    ingest_parser.add_argument("-r", "--recursive", action="store_true", help="Recursive")
    ingest_parser.add_argument("-f", "--force", action="store_true", help="Force re-ingestion")
    ingest_parser.add_argument("-w", "--workers", type=int, default=4, help="Worker threads")
    ingest_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=[],
        dest="tags",
        help="Collection tag to apply (repeatable, e.g. -t sphr-study -t cert-prep)",
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.set_defaults(func=cmd_status)

    # Check links command
    links_parser = subparsers.add_parser("check-links", help="Check for broken links")
    links_parser.add_argument("path", type=Path, help="Directory to scan")
    links_parser.add_argument("-r", "--recursive", action="store_true", default=True)
    links_parser.add_argument("-o", "--output", type=Path, help="Save report to file")
    links_parser.set_defaults(func=cmd_check_links)

    # Duplicates command
    dupes_parser = subparsers.add_parser("duplicates", help="Find duplicate content")
    dupes_parser.add_argument("path", type=Path, help="Directory to scan")
    dupes_parser.add_argument("-r", "--recursive", action="store_true", default=True)
    dupes_parser.set_defaults(func=cmd_duplicates)

    # Stale command
    stale_parser = subparsers.add_parser("stale", help="Find stale content")
    stale_parser.add_argument("path", type=Path, help="Directory to scan")
    stale_parser.add_argument("-d", "--days", type=int, default=365, help="Days threshold")
    stale_parser.add_argument("-r", "--recursive", action="store_true", default=True)
    stale_parser.set_defaults(func=cmd_stale)

    # Tag command
    tag_parser = subparsers.add_parser("tag", help="Auto-tag files")
    tag_parser.add_argument("path", type=Path, help="File or directory to tag")
    tag_parser.add_argument("-r", "--recursive", action="store_true", default=True)
    tag_parser.set_defaults(func=cmd_tag)

    # PII dictionary command
    pii_parser = subparsers.add_parser("pii", help="Manage custom PII dictionary")
    pii_sub = pii_parser.add_subparsers(dest="pii_action", help="PII actions")

    pii_list_parser = pii_sub.add_parser("list", help="List custom PII terms")
    pii_list_parser.set_defaults(func=cmd_pii)

    pii_add_parser = pii_sub.add_parser("add", help="Add a PII term")
    pii_add_parser.add_argument("term", help="PII term value")
    pii_add_parser.add_argument(
        "--type", default="CUSTOM", help="PII type (CUSTOM, SSN, EMAIL, PHONE, NAME, etc.)"
    )
    pii_add_parser.set_defaults(func=cmd_pii)

    pii_remove_parser = pii_sub.add_parser("remove", help="Remove a PII term")
    pii_remove_parser.add_argument("term", help="PII term to remove")
    pii_remove_parser.set_defaults(func=cmd_pii)

    # Health check command
    health_parser = subparsers.add_parser("health", help="Run system health checks")
    health_parser.add_argument(
        "--db", action="store_true", help="Database-only health check (quick or full)"
    )
    health_parser.add_argument(
        "--full", action="store_true", help="Full report with performance analysis (use with --db)"
    )
    health_parser.set_defaults(func=cmd_health)

    # Optimize database command
    optdb_parser = subparsers.add_parser("optimize-db", help="Optimize LanceDB database")
    optdb_parser.add_argument(
        "--report-only", action="store_true", help="Show health report without optimizing"
    )
    optdb_parser.set_defaults(func=cmd_optimize_db)

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Manage backups")
    backup_sub = backup_parser.add_subparsers(dest="backup_action", help="Backup actions")

    backup_create = backup_sub.add_parser("create", help="Create a backup")
    backup_create.add_argument("--name", help="Backup name (auto-generated if omitted)")
    backup_create.add_argument("--type", default="full", help="Backup type (full, incremental)")
    backup_create.set_defaults(func=cmd_backup)

    backup_list = backup_sub.add_parser("list", help="List backups")
    backup_list.set_defaults(func=cmd_backup)

    backup_restore = backup_sub.add_parser("restore", help="Restore from backup")
    backup_restore.add_argument("name", help="Backup name to restore")
    backup_restore.set_defaults(func=cmd_backup)

    backup_cleanup = backup_sub.add_parser("cleanup", help="Remove old backups")
    backup_cleanup.add_argument("--keep", type=int, default=5, help="Number of backups to keep")
    backup_cleanup.set_defaults(func=cmd_backup)

    # Knowledge graph command
    graph_parser = subparsers.add_parser("graph", help="Query the knowledge graph")
    graph_sub = graph_parser.add_subparsers(dest="graph_action", help="Graph actions")

    graph_stats = graph_sub.add_parser("stats", help="Show graph statistics")
    graph_stats.set_defaults(func=cmd_graph)

    graph_query = graph_sub.add_parser("query", help="Find entity connections")
    graph_query.add_argument("entity", help="Entity name to look up")
    graph_query.set_defaults(func=cmd_graph)

    graph_path = graph_sub.add_parser("path", help="Find path between entities")
    graph_path.add_argument("entity", help="Start entity")
    graph_path.add_argument("target", help="End entity")
    graph_path.add_argument("--hops", type=int, default=3, help="Max hops (default: 3)")
    graph_path.set_defaults(func=cmd_graph)

    # Episodic memory command
    mem_parser = subparsers.add_parser("memory", help="Manage episodic memory (user facts)")
    mem_parser.add_argument("--user", default="default", help="User ID (default: 'default')")
    mem_sub = mem_parser.add_subparsers(dest="memory_action", help="Memory actions")

    mem_list = mem_sub.add_parser("list", help="List stored facts")
    mem_list.set_defaults(func=cmd_memory)

    mem_add = mem_sub.add_parser("add", help="Add a fact")
    mem_add.add_argument("fact", help="Fact content")
    mem_add.add_argument(
        "--category",
        default="personal",
        help="Fact category (personal, preference, life_event, project, work, health, financial)",
    )
    mem_add.set_defaults(func=cmd_memory)

    mem_context = mem_sub.add_parser("context", help="Show context injection text")
    mem_context.set_defaults(func=cmd_memory)

    mem_export = mem_sub.add_parser("export", help="Export profile as JSON")
    mem_export.set_defaults(func=cmd_memory)

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("corerag").setLevel(logging.DEBUG)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
