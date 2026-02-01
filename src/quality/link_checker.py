"""
Link Rot Checker for PKM.

Detects and reports dead URLs in your knowledge base:
- Async HTTP HEAD requests for efficiency
- Caching to avoid re-checking known URLs
- Batch processing with rate limiting
- Detailed reports with fix suggestions
"""

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


class LinkStatus(Enum):
    """Status of a checked link."""
    OK = "ok"                      # 2xx response
    REDIRECT = "redirect"          # 3xx response
    NOT_FOUND = "not_found"        # 404
    FORBIDDEN = "forbidden"        # 403
    SERVER_ERROR = "server_error"  # 5xx
    TIMEOUT = "timeout"            # Request timed out
    DNS_ERROR = "dns_error"        # Could not resolve host
    SSL_ERROR = "ssl_error"        # Certificate issue
    CONNECTION_ERROR = "connection_error"  # Network error
    UNKNOWN = "unknown"            # Other error


@dataclass
class LinkCheckResult:
    """Result of checking a single link."""
    url: str
    status: LinkStatus
    status_code: Optional[int] = None
    final_url: Optional[str] = None  # After redirects
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def is_broken(self) -> bool:
        """Check if link is broken."""
        return self.status in {
            LinkStatus.NOT_FOUND,
            LinkStatus.SERVER_ERROR,
            LinkStatus.TIMEOUT,
            LinkStatus.DNS_ERROR,
            LinkStatus.SSL_ERROR,
            LinkStatus.CONNECTION_ERROR,
        }


@dataclass
class DocumentLinkReport:
    """Link report for a single document."""
    file_path: str
    total_links: int
    ok_links: int
    broken_links: int
    redirect_links: int
    links: List[Tuple[str, LinkCheckResult]]  # (url, result)

    @property
    def health_score(self) -> float:
        """Calculate link health score (0-100)."""
        if self.total_links == 0:
            return 100.0
        return (self.ok_links / self.total_links) * 100


@dataclass
class LinkRotReport:
    """Complete link rot report."""
    scan_started: datetime
    scan_completed: datetime
    documents_scanned: int
    total_links: int
    unique_links: int
    broken_links: int
    redirect_links: int
    by_document: List[DocumentLinkReport]
    broken_details: List[Tuple[str, str, LinkCheckResult]]  # (file, url, result)

    @property
    def overall_health(self) -> float:
        """Overall link health percentage."""
        if self.total_links == 0:
            return 100.0
        return ((self.total_links - self.broken_links) / self.total_links) * 100


class LinkExtractor:
    """Extract URLs from various document types."""

    # URL patterns
    MARKDOWN_LINK = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
    BARE_URL = re.compile(
        r'https?://[^\s<>\[\]()"\',;]+[^\s<>\[\]()"\',;.!?]'
    )
    HTML_HREF = re.compile(r'href=["\']([^"\']+)["\']')

    @classmethod
    def extract_urls(cls, content: str, file_type: str = "md") -> List[str]:
        """
        Extract URLs from content.

        Args:
            content: File content
            file_type: File extension

        Returns:
            List of unique URLs
        """
        urls: Set[str] = set()

        # Markdown links
        for match in cls.MARKDOWN_LINK.finditer(content):
            url = match.group(2).strip()
            if cls._is_valid_url(url):
                urls.add(url)

        # Bare URLs
        for match in cls.BARE_URL.finditer(content):
            url = match.group(0)
            if cls._is_valid_url(url):
                urls.add(url)

        # HTML hrefs (for HTML or mixed content)
        if file_type in {"html", "htm", "md"}:
            for match in cls.HTML_HREF.finditer(content):
                url = match.group(1)
                if cls._is_valid_url(url):
                    urls.add(url)

        return list(urls)

    @classmethod
    def _is_valid_url(cls, url: str) -> bool:
        """Check if URL is valid for checking."""
        try:
            parsed = urlparse(url)

            # Must have scheme and netloc
            if not parsed.scheme or not parsed.netloc:
                return False

            # Only http/https
            if parsed.scheme not in {"http", "https"}:
                return False

            # Skip localhost
            if parsed.netloc in {"localhost", "127.0.0.1", "0.0.0.0"}:
                return False

            # Skip internal anchors
            if url.startswith("#"):
                return False

            return True

        except Exception:
            return False


class LinkCache:
    """Cache for link check results."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cache_duration: timedelta = timedelta(days=7),
    ):
        """
        Initialize link cache.

        Args:
            cache_dir: Directory for cache storage
            cache_duration: How long to cache results
        """
        self.cache_dir = cache_dir or Path.home() / ".pkm" / "link_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_duration = cache_duration
        self._cache: Dict[str, LinkCheckResult] = {}
        self._load_cache()

    def get(self, url: str) -> Optional[LinkCheckResult]:
        """Get cached result for URL."""
        cache_key = self._url_key(url)
        result = self._cache.get(cache_key)

        if result:
            # Check if still valid
            age = datetime.now() - result.checked_at
            if age < self.cache_duration:
                return result
            else:
                # Expired
                del self._cache[cache_key]

        return None

    def put(self, url: str, result: LinkCheckResult) -> None:
        """Cache result for URL."""
        cache_key = self._url_key(url)
        self._cache[cache_key] = result
        self._save_cache()

    def invalidate(self, url: str) -> None:
        """Remove URL from cache."""
        cache_key = self._url_key(url)
        if cache_key in self._cache:
            del self._cache[cache_key]
            self._save_cache()

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._save_cache()

    def _url_key(self, url: str) -> str:
        """Generate cache key for URL."""
        return hashlib.md5(url.encode()).hexdigest()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        cache_file = self.cache_dir / "link_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                    for key, item in data.items():
                        self._cache[key] = LinkCheckResult(
                            url=item["url"],
                            status=LinkStatus(item["status"]),
                            status_code=item.get("status_code"),
                            final_url=item.get("final_url"),
                            response_time_ms=item.get("response_time_ms"),
                            error_message=item.get("error_message"),
                            checked_at=datetime.fromisoformat(item["checked_at"]),
                        )
                logger.info(f"Loaded {len(self._cache)} cached link results")
            except Exception as e:
                logger.warning(f"Failed to load link cache: {e}")

    def _save_cache(self) -> None:
        """Save cache to disk."""
        cache_file = self.cache_dir / "link_cache.json"
        try:
            data = {}
            for key, result in self._cache.items():
                data[key] = {
                    "url": result.url,
                    "status": result.status.value,
                    "status_code": result.status_code,
                    "final_url": result.final_url,
                    "response_time_ms": result.response_time_ms,
                    "error_message": result.error_message,
                    "checked_at": result.checked_at.isoformat(),
                }
            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save link cache: {e}")


class LinkChecker:
    """
    Check URLs for link rot.

    Features:
    - Async HTTP requests for speed
    - Result caching
    - Rate limiting
    - Batch processing
    """

    def __init__(
        self,
        cache: Optional[LinkCache] = None,
        timeout: float = 10.0,
        max_concurrent: int = 10,
        rate_limit_delay: float = 0.1,
        user_agent: str = "PKM-LinkChecker/1.0",
    ):
        """
        Initialize link checker.

        Args:
            cache: Link cache instance
            timeout: Request timeout in seconds
            max_concurrent: Max concurrent requests
            rate_limit_delay: Delay between requests (seconds)
            user_agent: User agent string
        """
        self.cache = cache or LinkCache()
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.rate_limit_delay = rate_limit_delay
        self.user_agent = user_agent

    async def check_url(
        self,
        url: str,
        session: aiohttp.ClientSession,
        use_cache: bool = True,
    ) -> LinkCheckResult:
        """
        Check a single URL.

        Args:
            url: URL to check
            session: aiohttp session
            use_cache: Whether to use cached results

        Returns:
            LinkCheckResult
        """
        # Check cache first
        if use_cache:
            cached = self.cache.get(url)
            if cached:
                return cached

        start_time = datetime.now()

        try:
            async with session.head(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

                # Determine status
                if 200 <= response.status < 300:
                    status = LinkStatus.OK
                elif 300 <= response.status < 400:
                    status = LinkStatus.REDIRECT
                elif response.status == 403:
                    status = LinkStatus.FORBIDDEN
                elif response.status == 404:
                    status = LinkStatus.NOT_FOUND
                elif response.status >= 500:
                    status = LinkStatus.SERVER_ERROR
                else:
                    status = LinkStatus.UNKNOWN

                result = LinkCheckResult(
                    url=url,
                    status=status,
                    status_code=response.status,
                    final_url=str(response.url) if str(response.url) != url else None,
                    response_time_ms=elapsed_ms,
                )

        except asyncio.TimeoutError:
            result = LinkCheckResult(
                url=url,
                status=LinkStatus.TIMEOUT,
                error_message=f"Request timed out after {self.timeout}s",
            )

        except aiohttp.ClientConnectorError as e:
            if "Name or service not known" in str(e) or "getaddrinfo" in str(e):
                result = LinkCheckResult(
                    url=url,
                    status=LinkStatus.DNS_ERROR,
                    error_message="Could not resolve hostname",
                )
            else:
                result = LinkCheckResult(
                    url=url,
                    status=LinkStatus.CONNECTION_ERROR,
                    error_message=str(e),
                )

        except aiohttp.ClientSSLError as e:
            result = LinkCheckResult(
                url=url,
                status=LinkStatus.SSL_ERROR,
                error_message=str(e),
            )

        except Exception as e:
            result = LinkCheckResult(
                url=url,
                status=LinkStatus.UNKNOWN,
                error_message=str(e),
            )

        # Cache result
        self.cache.put(url, result)

        return result

    async def check_urls(
        self,
        urls: List[str],
        use_cache: bool = True,
    ) -> Dict[str, LinkCheckResult]:
        """
        Check multiple URLs concurrently.

        Args:
            urls: URLs to check
            use_cache: Whether to use cached results

        Returns:
            Dict mapping URL to result
        """
        results: Dict[str, LinkCheckResult] = {}
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def check_with_limit(url: str, session: aiohttp.ClientSession):
            async with semaphore:
                result = await self.check_url(url, session, use_cache)
                await asyncio.sleep(self.rate_limit_delay)
                return url, result

        headers = {"User-Agent": self.user_agent}
        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = [check_with_limit(url, session) for url in urls]
            completed = await asyncio.gather(*tasks, return_exceptions=True)

            for item in completed:
                if isinstance(item, Exception):
                    logger.error(f"Unexpected error: {item}")
                else:
                    url, result = item
                    results[url] = result

        return results

    async def scan_directory(
        self,
        directory: Path,
        recursive: bool = True,
        file_types: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> LinkRotReport:
        """
        Scan a directory for link rot.

        Args:
            directory: Directory to scan
            recursive: Scan recursively
            file_types: File extensions to scan (default: md, txt, html)
            use_cache: Whether to use cached results

        Returns:
            LinkRotReport
        """
        scan_started = datetime.now()

        if file_types is None:
            file_types = ["md", "txt", "html", "htm"]

        # Collect all URLs from all files
        file_urls: Dict[str, List[str]] = {}  # file_path -> [urls]
        all_urls: Set[str] = set()

        pattern = "**/*" if recursive else "*"
        for file_path in Path(directory).glob(pattern):
            if file_path.is_file():
                ext = file_path.suffix.lower().lstrip(".")
                if ext in file_types:
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        urls = LinkExtractor.extract_urls(content, ext)
                        if urls:
                            file_urls[str(file_path)] = urls
                            all_urls.update(urls)
                    except Exception as e:
                        logger.warning(f"Error reading {file_path}: {e}")

        # Check all unique URLs
        url_results = await self.check_urls(list(all_urls), use_cache)

        # Build per-document reports
        doc_reports: List[DocumentLinkReport] = []
        all_broken: List[Tuple[str, str, LinkCheckResult]] = []

        for file_path, urls in file_urls.items():
            ok_count = 0
            broken_count = 0
            redirect_count = 0
            link_results: List[Tuple[str, LinkCheckResult]] = []

            for url in urls:
                result = url_results.get(url)
                if result:
                    link_results.append((url, result))
                    if result.status == LinkStatus.OK:
                        ok_count += 1
                    elif result.status == LinkStatus.REDIRECT:
                        redirect_count += 1
                    elif result.is_broken:
                        broken_count += 1
                        all_broken.append((file_path, url, result))

            doc_reports.append(DocumentLinkReport(
                file_path=file_path,
                total_links=len(urls),
                ok_links=ok_count,
                broken_links=broken_count,
                redirect_links=redirect_count,
                links=link_results,
            ))

        scan_completed = datetime.now()

        return LinkRotReport(
            scan_started=scan_started,
            scan_completed=scan_completed,
            documents_scanned=len(file_urls),
            total_links=sum(len(urls) for urls in file_urls.values()),
            unique_links=len(all_urls),
            broken_links=len(all_broken),
            redirect_links=sum(r.redirect_links for r in doc_reports),
            by_document=doc_reports,
            broken_details=all_broken,
        )


def format_report(report: LinkRotReport) -> str:
    """Format link rot report as markdown."""
    lines = [
        "# Link Rot Report",
        "",
        f"**Scan Time:** {report.scan_started.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Duration:** {(report.scan_completed - report.scan_started).total_seconds():.1f}s",
        "",
        "## Summary",
        "",
        f"- Documents scanned: {report.documents_scanned}",
        f"- Total links: {report.total_links}",
        f"- Unique links: {report.unique_links}",
        f"- Broken links: {report.broken_links}",
        f"- Overall health: {report.overall_health:.1f}%",
        "",
    ]

    if report.broken_details:
        lines.extend([
            "## Broken Links",
            "",
        ])

        # Group by file
        by_file: Dict[str, List[Tuple[str, LinkCheckResult]]] = {}
        for file_path, url, result in report.broken_details:
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append((url, result))

        for file_path, broken in by_file.items():
            lines.append(f"### {Path(file_path).name}")
            lines.append("")
            for url, result in broken:
                status_icon = {
                    LinkStatus.NOT_FOUND: "❌",
                    LinkStatus.TIMEOUT: "⏱️",
                    LinkStatus.DNS_ERROR: "🔍",
                    LinkStatus.SSL_ERROR: "🔒",
                    LinkStatus.SERVER_ERROR: "💥",
                    LinkStatus.CONNECTION_ERROR: "🔌",
                }.get(result.status, "❓")
                lines.append(f"- {status_icon} `{url}`")
                lines.append(f"  - Status: {result.status.value}")
                if result.error_message:
                    lines.append(f"  - Error: {result.error_message}")
            lines.append("")

    return "\n".join(lines)


# Convenience function
async def check_links(
    directory: Path,
    recursive: bool = True,
    file_types: Optional[List[str]] = None,
) -> LinkRotReport:
    """
    Quick link rot check for a directory.

    Args:
        directory: Directory to scan
        recursive: Scan recursively
        file_types: File extensions to check

    Returns:
        LinkRotReport
    """
    checker = LinkChecker()
    return await checker.scan_directory(directory, recursive, file_types)
