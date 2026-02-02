"""
Health Dashboard for CoreRag.

A lightweight web dashboard for monitoring CoreRag system health:
- Memory and CPU usage
- Database statistics
- Ingestion queue status
- Query analytics
- Content freshness overview
- Recent activity log
"""

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import psutil

logger = logging.getLogger(__name__)


@dataclass
class SystemMetrics:
    """Current system metrics."""
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    cpu_percent: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    timestamp: str


@dataclass
class DatabaseMetrics:
    """Database statistics."""
    connected: bool
    tables: List[str]
    total_chunks: int
    total_size_mb: float
    last_updated: Optional[str]


@dataclass
class IngestionMetrics:
    """Ingestion queue status."""
    queued: int
    processing: int
    completed_today: int
    failed_today: int
    processing_files: List[str]


@dataclass
class ContentMetrics:
    """Content health metrics."""
    total_files: int
    fresh_count: int
    stale_count: int
    avg_age_days: float
    broken_links: int
    duplicates: int


@dataclass
class HealthReport:
    """Complete health report."""
    status: str  # "healthy", "warning", "critical"
    system: SystemMetrics
    database: DatabaseMetrics
    ingestion: IngestionMetrics
    content: ContentMetrics
    alerts: List[str]


class MetricsCollector:
    """Collect metrics from various CoreRag subsystems."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        state_dir: Optional[Path] = None,
    ):
        self.db_path = db_path or Path.home() / ".corerag" / "lancedb"
        self.state_dir = state_dir or Path.home() / ".corerag"

    def get_system_metrics(self) -> SystemMetrics:
        """Get current system metrics."""
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return SystemMetrics(
            memory_percent=memory.percent,
            memory_used_gb=memory.used / (1024**3),
            memory_total_gb=memory.total / (1024**3),
            cpu_percent=psutil.cpu_percent(interval=0.1),
            disk_percent=disk.percent,
            disk_used_gb=disk.used / (1024**3),
            disk_total_gb=disk.total / (1024**3),
            timestamp=datetime.now().isoformat(),
        )

    def get_database_metrics(self) -> DatabaseMetrics:
        """Get database statistics."""
        try:
            import lancedb

            if not self.db_path.exists():
                return DatabaseMetrics(
                    connected=False,
                    tables=[],
                    total_chunks=0,
                    total_size_mb=0,
                    last_updated=None,
                )

            db = lancedb.connect(str(self.db_path))
            tables = db.table_names()

            total_chunks = 0
            if "chunks" in tables:
                table = db.open_table("chunks")
                total_chunks = table.count_rows()

            # Calculate size
            total_size = sum(
                f.stat().st_size
                for f in self.db_path.rglob("*")
                if f.is_file()
            )

            return DatabaseMetrics(
                connected=True,
                tables=tables,
                total_chunks=total_chunks,
                total_size_mb=total_size / (1024**2),
                last_updated=datetime.now().isoformat(),
            )

        except Exception as e:
            logger.warning(f"Failed to get database metrics: {e}")
            return DatabaseMetrics(
                connected=False,
                tables=[],
                total_chunks=0,
                total_size_mb=0,
                last_updated=None,
            )

    def get_ingestion_metrics(self) -> IngestionMetrics:
        """Get ingestion queue status."""
        # Read from state file if available
        state_file = self.state_dir / "ingestion" / "pipeline_state.json"

        queued = 0
        processing = 0
        completed_today = 0
        failed_today = 0
        processing_files = []

        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    completed_today = state.get("total_processed", 0)
            except Exception:
                pass

        return IngestionMetrics(
            queued=queued,
            processing=processing,
            completed_today=completed_today,
            failed_today=failed_today,
            processing_files=processing_files,
        )

    def get_content_metrics(self) -> ContentMetrics:
        """Get content health metrics."""
        # Read from cached state if available
        cache_file = self.state_dir / "metrics_cache.json"

        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                    return ContentMetrics(**data.get("content", {}))
            except Exception:
                pass

        return ContentMetrics(
            total_files=0,
            fresh_count=0,
            stale_count=0,
            avg_age_days=0,
            broken_links=0,
            duplicates=0,
        )

    def get_health_report(self) -> HealthReport:
        """Generate complete health report."""
        system = self.get_system_metrics()
        database = self.get_database_metrics()
        ingestion = self.get_ingestion_metrics()
        content = self.get_content_metrics()

        alerts = []

        # Check for issues
        if system.memory_percent > 85:
            alerts.append(f"High memory usage: {system.memory_percent:.1f}%")
        if system.cpu_percent > 90:
            alerts.append(f"High CPU usage: {system.cpu_percent:.1f}%")
        if system.disk_percent > 90:
            alerts.append(f"Low disk space: {100 - system.disk_percent:.1f}% free")
        if not database.connected:
            alerts.append("Database not connected")
        if content.broken_links > 10:
            alerts.append(f"{content.broken_links} broken links detected")
        if content.stale_count > 100:
            alerts.append(f"{content.stale_count} stale files need review")

        # Determine overall status
        if len(alerts) == 0:
            status = "healthy"
        elif any("High memory" in a or "Database not" in a for a in alerts):
            status = "critical"
        else:
            status = "warning"

        return HealthReport(
            status=status,
            system=system,
            database=database,
            ingestion=ingestion,
            content=content,
            alerts=alerts,
        )


# === HTML Dashboard ===

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CoreRag Health Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #e0e0e0;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #333;
        }
        .header h1 {
            color: #fff;
            font-size: 24px;
        }
        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 12px;
        }
        .status-healthy { background: #22c55e; color: #000; }
        .status-warning { background: #eab308; color: #000; }
        .status-critical { background: #ef4444; color: #fff; }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #333;
        }
        .card-title {
            font-size: 14px;
            color: #888;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .metric-label { color: #aaa; }
        .metric-value { font-weight: 600; font-size: 18px; }

        .progress-bar {
            height: 8px;
            background: #333;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 8px;
        }
        .progress-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        .progress-green { background: linear-gradient(90deg, #22c55e, #16a34a); }
        .progress-yellow { background: linear-gradient(90deg, #eab308, #ca8a04); }
        .progress-red { background: linear-gradient(90deg, #ef4444, #dc2626); }

        .alerts {
            margin-top: 20px;
        }
        .alert {
            background: #2d1f1f;
            border-left: 4px solid #ef4444;
            padding: 12px;
            margin-bottom: 8px;
            border-radius: 0 8px 8px 0;
        }
        .alert-warning {
            background: #2d2a1f;
            border-left-color: #eab308;
        }

        .timestamp {
            color: #666;
            font-size: 12px;
            margin-top: 20px;
            text-align: center;
        }

        .refresh-btn {
            background: #333;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        .refresh-btn:hover { background: #444; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🧠 CoreRag Health Dashboard</h1>
        <div style="display: flex; gap: 10px; align-items: center;">
            <span id="status-badge" class="status-badge">Loading...</span>
            <button class="refresh-btn" onclick="refreshData()">↻ Refresh</button>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-title">💾 Memory</div>
            <div class="metric">
                <span class="metric-label">Usage</span>
                <span class="metric-value" id="memory-percent">--</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" id="memory-bar" style="width: 0%"></div>
            </div>
            <div class="metric" style="margin-top: 15px;">
                <span class="metric-label">Used / Total</span>
                <span id="memory-detail">--</span>
            </div>
        </div>

        <div class="card">
            <div class="card-title">⚡ CPU</div>
            <div class="metric">
                <span class="metric-label">Usage</span>
                <span class="metric-value" id="cpu-percent">--</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" id="cpu-bar" style="width: 0%"></div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">🗄️ Database</div>
            <div class="metric">
                <span class="metric-label">Status</span>
                <span class="metric-value" id="db-status">--</span>
            </div>
            <div class="metric">
                <span class="metric-label">Chunks Indexed</span>
                <span id="db-chunks">--</span>
            </div>
            <div class="metric">
                <span class="metric-label">Size</span>
                <span id="db-size">--</span>
            </div>
        </div>

        <div class="card">
            <div class="card-title">📥 Ingestion</div>
            <div class="metric">
                <span class="metric-label">Queued</span>
                <span class="metric-value" id="ingest-queued">--</span>
            </div>
            <div class="metric">
                <span class="metric-label">Completed Today</span>
                <span id="ingest-completed">--</span>
            </div>
        </div>

        <div class="card">
            <div class="card-title">📊 Content Health</div>
            <div class="metric">
                <span class="metric-label">Total Files</span>
                <span class="metric-value" id="content-total">--</span>
            </div>
            <div class="metric">
                <span class="metric-label">Fresh / Stale</span>
                <span id="content-freshness">--</span>
            </div>
            <div class="metric">
                <span class="metric-label">Broken Links</span>
                <span id="content-links">--</span>
            </div>
        </div>

        <div class="card">
            <div class="card-title">💿 Disk</div>
            <div class="metric">
                <span class="metric-label">Usage</span>
                <span class="metric-value" id="disk-percent">--</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" id="disk-bar" style="width: 0%"></div>
            </div>
        </div>
    </div>

    <div class="alerts" id="alerts-container"></div>

    <div class="timestamp" id="timestamp">Last updated: --</div>

    <script>
        function getProgressClass(value) {
            if (value < 60) return 'progress-green';
            if (value < 80) return 'progress-yellow';
            return 'progress-red';
        }

        function updateDashboard(data) {
            // Status badge
            const badge = document.getElementById('status-badge');
            badge.textContent = data.status.toUpperCase();
            badge.className = 'status-badge status-' + data.status;

            // Memory
            document.getElementById('memory-percent').textContent =
                data.system.memory_percent.toFixed(1) + '%';
            document.getElementById('memory-detail').textContent =
                data.system.memory_used_gb.toFixed(1) + ' GB / ' +
                data.system.memory_total_gb.toFixed(1) + ' GB';
            const memBar = document.getElementById('memory-bar');
            memBar.style.width = data.system.memory_percent + '%';
            memBar.className = 'progress-fill ' + getProgressClass(data.system.memory_percent);

            // CPU
            document.getElementById('cpu-percent').textContent =
                data.system.cpu_percent.toFixed(1) + '%';
            const cpuBar = document.getElementById('cpu-bar');
            cpuBar.style.width = data.system.cpu_percent + '%';
            cpuBar.className = 'progress-fill ' + getProgressClass(data.system.cpu_percent);

            // Disk
            document.getElementById('disk-percent').textContent =
                data.system.disk_percent.toFixed(1) + '%';
            const diskBar = document.getElementById('disk-bar');
            diskBar.style.width = data.system.disk_percent + '%';
            diskBar.className = 'progress-fill ' + getProgressClass(data.system.disk_percent);

            // Database
            document.getElementById('db-status').textContent =
                data.database.connected ? '✓ Connected' : '✗ Disconnected';
            document.getElementById('db-chunks').textContent =
                data.database.total_chunks.toLocaleString();
            document.getElementById('db-size').textContent =
                data.database.total_size_mb.toFixed(1) + ' MB';

            // Ingestion
            document.getElementById('ingest-queued').textContent = data.ingestion.queued;
            document.getElementById('ingest-completed').textContent = data.ingestion.completed_today;

            // Content
            document.getElementById('content-total').textContent =
                data.content.total_files.toLocaleString();
            document.getElementById('content-freshness').textContent =
                data.content.fresh_count + ' / ' + data.content.stale_count;
            document.getElementById('content-links').textContent = data.content.broken_links;

            // Alerts
            const alertsContainer = document.getElementById('alerts-container');
            alertsContainer.innerHTML = '';
            if (data.alerts.length > 0) {
                data.alerts.forEach(alert => {
                    const div = document.createElement('div');
                    div.className = alert.includes('High') ? 'alert' : 'alert alert-warning';
                    div.textContent = '⚠ ' + alert;
                    alertsContainer.appendChild(div);
                });
            }

            // Timestamp
            document.getElementById('timestamp').textContent =
                'Last updated: ' + new Date().toLocaleTimeString();
        }

        async function refreshData() {
            try {
                const response = await fetch('/api/health');
                const data = await response.json();
                updateDashboard(data);
            } catch (error) {
                console.error('Failed to fetch health data:', error);
            }
        }

        // Initial load and auto-refresh
        refreshData();
        setInterval(refreshData, 5000);
    </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard."""

    collector: MetricsCollector = None

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())

        elif parsed.path == "/api/health":
            report = self.collector.get_health_report()
            data = {
                "status": report.status,
                "system": asdict(report.system),
                "database": asdict(report.database),
                "ingestion": asdict(report.ingestion),
                "content": asdict(report.content),
                "alerts": report.alerts,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        else:
            self.send_response(404)
            self.end_headers()


class HealthDashboard:
    """
    Health Dashboard server.

    Features:
    - Real-time system metrics
    - Database statistics
    - Ingestion queue status
    - Content health overview
    - Auto-refresh via JavaScript
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        db_path: Optional[Path] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize dashboard.

        Args:
            host: Server host
            port: Server port
            db_path: Database path
            state_dir: State directory
        """
        self.host = host
        self.port = port
        self.collector = MetricsCollector(db_path, state_dir)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start dashboard server in background thread."""
        DashboardHandler.collector = self.collector

        self._server = HTTPServer((self.host, self.port), DashboardHandler)

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

        logger.info(f"Dashboard running at http://{self.host}:{self.port}")

    def stop(self) -> None:
        """Stop dashboard server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            logger.info("Dashboard stopped")

    def get_url(self) -> str:
        """Get dashboard URL."""
        return f"http://{self.host}:{self.port}"


# Convenience function
def start_dashboard(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> HealthDashboard:
    """
    Start health dashboard.

    Args:
        host: Server host
        port: Server port
        open_browser: Open browser automatically

    Returns:
        HealthDashboard instance
    """
    dashboard = HealthDashboard(host=host, port=port)
    dashboard.start()

    if open_browser:
        import webbrowser
        webbrowser.open(dashboard.get_url())

    return dashboard


if __name__ == "__main__":
    # Run standalone
    dashboard = start_dashboard(open_browser=True)
    print(f"Dashboard running at {dashboard.get_url()}")
    print("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        dashboard.stop()
