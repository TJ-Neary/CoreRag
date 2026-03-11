"""
CoreRag macOS Menu Bar App.

Shows a "CR" icon in the menu bar. Click to access the dashboard,
trigger ingestion, and monitor processing status.

Auto-starts the server if it detects it's not running.
The icon circle fills with neon green (#39FF14) during active ingestion.
"""

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import rumps

from src.config import SERVER_HOST, SERVER_PORT, SERVER_PORT_FILE


def _get_dashboard_url() -> str:
    """Read the active server port from the port file, fallback to configured default."""
    port = SERVER_PORT
    if SERVER_PORT_FILE.exists():
        try:
            port = int(SERVER_PORT_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return f"http://{SERVER_HOST}:{port}"


# Asset paths (relative to project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ICON_IDLE = str(PROJECT_ROOT / "assets" / "menubar_icon.png")
ICON_ACTIVE = str(PROJECT_ROOT / "assets" / "menubar_icon_active.png")
ICON_DOCK = str(PROJECT_ROOT / "assets" / "dock_icon.png")

# Server auto-start cooldown (seconds) — don't spam restart attempts
_SERVER_START_COOLDOWN = 30


class CoreRagApp(rumps.App):
    """CoreRag menu bar application."""

    def __init__(self):
        # Use text title as fallback if icon assets don't exist yet
        icon_path = ICON_IDLE if Path(ICON_IDLE).exists() else None
        super().__init__(
            name="CoreRag",
            title="CR" if not icon_path else None,
            icon=icon_path,
            quit_button=None,  # We'll add our own
        )

        # Set dock icon (replaces generic Python icon)
        self._set_dock_icon()

        self.menu = [
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            rumps.MenuItem("Start Ingestion", callback=self.start_ingestion),
            None,  # separator
            rumps.MenuItem("Start Server", callback=self.manual_start_server),
            rumps.MenuItem("Status: Starting...", callback=None),
            None,  # separator
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        self._status_item = self.menu["Status: Starting..."]
        self._start_server_item = self.menu["Start Server"]
        self._is_active = False
        self._server_process = None
        self._last_start_attempt = 0.0
        self._server_was_available = False
        self._startup_time = time.time()

        # Start polling timer (every 3 seconds)
        self._timer = rumps.Timer(self._poll_status, 3)
        self._timer.start()

    def open_dashboard(self, _):
        """Open the CoreRag dashboard in the default browser."""
        webbrowser.open(_get_dashboard_url())

    def start_ingestion(self, _):
        """Trigger batch ingestion via the dashboard API."""
        try:
            import urllib.request

            req = urllib.request.Request(f"{_get_dashboard_url()}/api/start-batch", method="POST")
            with urllib.request.urlopen(req, timeout=5):  # nosec B310
                pass
            rumps.notification(
                title="CoreRag",
                subtitle="Ingestion Started",
                message="Processing inbox files...",
            )
        except Exception as e:
            rumps.notification(
                title="CoreRag",
                subtitle="Error",
                message=f"Could not start ingestion: {e}",
            )

    def manual_start_server(self, _):
        """Manually start the server from the menu."""
        self._start_server()

    def quit_app(self, _):
        """Quit the menu bar app."""
        rumps.quit_application()

    def _is_server_process_running(self) -> bool:
        """Check if a src.server process already exists."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "src.server"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _start_server(self) -> bool:
        """Start the CoreRag server as a background process.

        Returns True if a start was attempted, False if on cooldown or already running.
        """
        now = time.time()
        if now - self._last_start_attempt < _SERVER_START_COOLDOWN:
            return False

        # Don't start if a server process already exists
        if self._is_server_process_running():
            self._last_start_attempt = now
            self._status_item.title = "Status: Server starting..."
            return False

        self._last_start_attempt = now
        self._status_item.title = "Status: Starting server..."

        # Find Python interpreter — prefer venv
        venv_python = PROJECT_ROOT / "venv" / "bin" / "python3"
        if venv_python.exists():
            python_cmd = str(venv_python)
        else:
            python_cmd = sys.executable

        # Start server as detached subprocess
        log_dir = Path.home() / ".corerag" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "server.log"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

        try:
            with open(log_file, "a") as lf:
                self._server_process = subprocess.Popen(
                    [python_cmd, "-m", "src.server"],
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=lf,
                    stderr=lf,
                    start_new_session=True,
                )
            return True
        except Exception:
            self._status_item.title = "Status: Server failed to start"
            return False

    def _poll_status(self, _):
        """Poll the server for ingestion status and update the icon."""
        try:
            import json
            import urllib.request

            # Check batch processing status
            req = urllib.request.Request(f"{_get_dashboard_url()}/api/progress", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310
                data = json.loads(resp.read())

            # Server is available
            if not self._server_was_available:
                self._server_was_available = True
                self._start_server_item.title = "Restart Server"

            status = data.get("status", "idle")
            total = data.get("total", 0)
            processed = data.get("processed", 0)
            current = data.get("current_file", "")

            if status in ("processing", "paused"):
                self._set_active(True)
                if current:
                    self._status_item.title = f"Processing: {current} ({processed}/{total})"
                else:
                    self._status_item.title = f"Processing: {processed}/{total}"
            elif status == "complete" and self._is_active:
                self._set_active(False)
                self._status_item.title = f"Complete: {total} files"
                rumps.notification(
                    title="CoreRag",
                    subtitle="Ingestion Complete",
                    message=f"Processed {total} files.",
                )
            else:
                # Also check commit status
                try:
                    req2 = urllib.request.Request(
                        f"{_get_dashboard_url()}/api/commit-progress", method="GET"
                    )
                    with urllib.request.urlopen(req2, timeout=2) as resp2:  # nosec B310
                        commit_data = json.loads(resp2.read())
                    commit_status = commit_data.get("status", "idle")
                    if commit_status in ("running", "paused"):
                        self._set_active(True)
                        committed = commit_data.get("committed", 0)
                        commit_total = commit_data.get("total", 0)
                        self._status_item.title = f"Committing: {committed}/{commit_total}"
                        return
                except Exception:
                    pass

                self._set_active(False)
                self._status_item.title = "Status: Idle"

        except Exception:
            # Server not running — try to auto-start it
            self._set_active(False)
            self._server_was_available = False
            self._start_server_item.title = "Start Server"

            # Grace period: don't auto-start in the first 5 seconds after app launch
            # (the server may still be initializing from run_menubar.sh)
            if time.time() - self._startup_time < 5:
                self._status_item.title = "Status: Connecting..."
            elif self._start_server():
                self._status_item.title = "Status: Starting server..."
            else:
                self._status_item.title = "Status: Server starting..."

    @staticmethod
    def _set_dock_icon():
        """Set the dock icon to the CoreRag CR icon (replaces generic Python icon)."""
        if not Path(ICON_DOCK).exists():
            return
        try:
            from AppKit import NSApplication, NSImage

            icon = NSImage.alloc().initWithContentsOfFile_(ICON_DOCK)
            if icon:
                NSApplication.sharedApplication().setApplicationIconImage_(icon)
        except Exception:
            pass  # Non-critical — generic Python icon is fine as fallback

    def _set_active(self, active: bool):
        """Switch between idle and active icon states."""
        if active == self._is_active:
            return
        self._is_active = active

        if active:
            icon_path = ICON_ACTIVE if Path(ICON_ACTIVE).exists() else None
            if icon_path:
                self.icon = icon_path
                self.title = None
            else:
                self.title = "CR*"  # Fallback: asterisk indicates activity
        else:
            icon_path = ICON_IDLE if Path(ICON_IDLE).exists() else None
            if icon_path:
                self.icon = icon_path
                self.title = None
            else:
                self.title = "CR"


def main():
    """Launch the CoreRag menu bar app."""
    CoreRagApp().run()


if __name__ == "__main__":
    main()
