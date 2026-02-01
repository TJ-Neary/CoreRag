#!/usr/bin/env python3
"""
PKM Command-Line Interface.

A comprehensive CLI for manual PKM operations:
- Search and query
- File ingestion
- System status
- Maintenance tasks
- Configuration
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("pkm-cli")


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
        from src.search.hyde import create_hyde_expander

        print_header(f"Searching: {args.query}")

        # Initialize services
        embedding_service = create_embedding_service()

        # Simple embedding search (without full infrastructure)
        query_embedding = embedding_service.embed_query(args.query)

        # Connect to LanceDB
        import lancedb
        db_path = args.db_path or Path.home() / ".pkm" / "lancedb"
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

    except Exception as e:
        print_error(f"Search failed: {e}")
        logger.exception("Search error")
        return 1


# === Ingest Command ===

def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest files or directories."""
    try:
        from src.ingestion.pipeline import IngestionPipeline, FileTypeDetector

        target = Path(args.path)
        if not target.exists():
            print_error(f"Path not found: {target}")
            return 1

        print_header(f"Ingesting: {target}")

        pipeline = IngestionPipeline(
            enable_watch=False,
            max_workers=args.workers,
        )

        if target.is_file():
            job = pipeline.add_file(target, force=args.force)
            if job:
                print_success(f"Queued: {target.name} ({job.file_type.value})")
            else:
                print_warning(f"Skipped: {target.name}")
        else:
            count = pipeline.add_directory(target, recursive=args.recursive)
            print_success(f"Queued {count} files")

        # Start processing
        print_info("Processing...")
        pipeline.start()

        # Wait for completion (simple approach)
        import time
        max_wait = 300  # 5 minutes
        start = time.time()

        while time.time() - start < max_wait:
            status = pipeline.get_queue_status()
            if status["queued"] == 0 and status["processing"] == 0:
                break
            time.sleep(1)

        pipeline.stop()

        # Show results
        results = pipeline.get_recent_results(limit=50)
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        print()
        print_success(f"Completed: {success_count} files")
        if fail_count > 0:
            print_warning(f"Failed: {fail_count} files")

        return 0

    except Exception as e:
        print_error(f"Ingestion failed: {e}")
        logger.exception("Ingestion error")
        return 1


# === Status Command ===

def cmd_status(args: argparse.Namespace) -> int:
    """Show system status."""
    try:
        import psutil

        print_header("PKM System Status")

        # Memory
        memory = psutil.virtual_memory()
        mem_percent = memory.percent
        mem_color = Colors.GREEN if mem_percent < 60 else Colors.YELLOW if mem_percent < 80 else Colors.RED
        print(f"\nMemory: {color(f'{mem_percent:.1f}%', mem_color)} used "
              f"({memory.used / (1024**3):.1f}GB / {memory.total / (1024**3):.1f}GB)")

        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_color = Colors.GREEN if cpu_percent < 50 else Colors.YELLOW if cpu_percent < 80 else Colors.RED
        print(f"CPU: {color(f'{cpu_percent:.1f}%', cpu_color)} used")

        # Database
        db_path = Path.home() / ".pkm" / "lancedb"
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
        state_dir = Path.home() / ".pkm"
        if state_dir.exists():
            total_size = sum(f.stat().st_size for f in state_dir.rglob("*") if f.is_file())
            print(f"\nState directory: {total_size / (1024**2):.1f} MB")

        return 0

    except Exception as e:
        print_error(f"Status check failed: {e}")
        return 1


# === Check Links Command ===

def cmd_check_links(args: argparse.Namespace) -> int:
    """Check for broken links."""
    try:
        from src.quality.link_checker import LinkChecker, format_report

        target = Path(args.path)
        if not target.exists():
            print_error(f"Path not found: {target}")
            return 1

        print_header(f"Checking links in: {target}")

        checker = LinkChecker()

        # Run async check
        report = asyncio.run(checker.scan_directory(
            target,
            recursive=args.recursive,
        ))

        # Print summary
        print(f"\nScanned {report.documents_scanned} documents")
        print(f"Found {report.total_links} total links ({report.unique_links} unique)")

        health_color = Colors.GREEN if report.overall_health > 90 else Colors.YELLOW if report.overall_health > 70 else Colors.RED
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

    except Exception as e:
        print_error(f"Link check failed: {e}")
        logger.exception("Link check error")
        return 1


# === Find Duplicates Command ===

def cmd_duplicates(args: argparse.Namespace) -> int:
    """Find duplicate content."""
    try:
        from src.quality.duplicate_detector import DuplicateDetector

        target = Path(args.path)
        if not target.exists():
            print_error(f"Path not found: {target}")
            return 1

        print_header(f"Finding duplicates in: {target}")

        detector = DuplicateDetector()
        report = detector.scan_directory(
            target,
            recursive=args.recursive,
        )

        total_dupes = report.exact_duplicates + report.near_duplicates + report.semantic_duplicates
        print(f"\nScanned {report.total_files} files")
        print(f"Found {total_dupes} duplicates "
              f"(exact: {report.exact_duplicates}, near: {report.near_duplicates}, "
              f"semantic: {report.semantic_duplicates})")
        print(f"Potential savings: {report.space_reclaimable_bytes / (1024 * 1024):.1f} MB")

        if report.matches:
            print("\nDuplicate pairs:")
            for i, match in enumerate(report.matches[:10], 1):
                print(f"\n{color(f'Pair {i}:', Colors.BOLD)}")
                print(f"  File 1: {Path(match.file1).name}")
                print(f"  File 2: {Path(match.file2).name}")
                print(f"    Similarity: {match.similarity:.1%} ({match.match_type})")

        return 0

    except Exception as e:
        print_error(f"Duplicate check failed: {e}")
        logger.exception("Duplicate check error")
        return 1


# === Find Stale Command ===

def cmd_stale(args: argparse.Namespace) -> int:
    """Find stale content."""
    try:
        from src.quality.freshness import FreshnessIndicator

        target = Path(args.path)
        if not target.exists():
            print_error(f"Path not found: {target}")
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
        print(f"\nSummary:")
        print(f"  Total files: {summary['total_files']}")
        print(f"  Average age: {summary['avg_age_days']:.0f} days")
        print(f"  Fresh (<7 days): {summary['fresh_percentage']:.1f}%")

        return 0

    except Exception as e:
        print_error(f"Stale check failed: {e}")
        logger.exception("Stale check error")
        return 1


# === Tag Command ===

def cmd_tag(args: argparse.Namespace) -> int:
    """Auto-tag files."""
    try:
        from src.classification.auto_tagger import AutoTagger

        target = Path(args.path)
        if not target.exists():
            print_error(f"Path not found: {target}")
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
            all_tags = {}
            for result in results.values():
                for tag in result.assigned_tags:
                    all_tags[tag] = all_tags.get(tag, 0) + 1

            if all_tags:
                print("\nTag distribution:")
                for tag, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]:
                    print(f"  {tag}: {count}")

        return 0

    except Exception as e:
        print_error(f"Tagging failed: {e}")
        logger.exception("Tagging error")
        return 1


# === PII Dictionary Command ===

def cmd_pii(args: argparse.Namespace) -> int:
    """Manage custom PII dictionary."""
    import yaml

    pii_path = Path.home() / ".pkm" / "pii_terms.yaml"

    if not args.pii_action:
        print_error("Usage: pkm pii {list|add|remove}")
        return 1

    if args.pii_action == "list":
        if not pii_path.exists():
            print_info("No custom PII terms defined.")
            print_info(f"File location: {pii_path}")
            print_info("Add terms with: pkm pii add <term> --type TYPE")
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
        pii_path.parent.mkdir(parents=True, exist_ok=True)

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
        with open(pii_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        print_success(f"Added PII term: [{args.type.upper()}] {args.term}")
        print_info(f"Saved to {pii_path}")
        return 0

    elif args.pii_action == "remove":
        if not pii_path.exists():
            print_error("No PII terms file found.")
            return 1

        with open(pii_path) as f:
            data = yaml.safe_load(f) or {"terms": []}

        original_count = len(data.get("terms", []))
        data["terms"] = [
            t for t in data.get("terms", [])
            if t.get("value", "").lower() != args.term.lower()
        ]

        if len(data["terms"]) == original_count:
            print_warning(f"Term not found: {args.term}")
            return 1

        with open(pii_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        print_success(f"Removed PII term: {args.term}")
        return 0

    else:
        print_error("Usage: pkm pii {list|add|remove}")
        return 1


# === Main ===

def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="pkm",
        description="Personal Knowledge Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v", "--verbose",
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

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
