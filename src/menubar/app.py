"""
CoreRag macOS Menu Bar App.

Shows a "CR" icon in the menu bar. Click to access the dashboard,
trigger ingestion, and monitor processing status.

The icon circle fills with neon green (#39FF14) during active ingestion.
"""

import webbrowser
from pathlib import Path

import rumps

DASHBOARD_URL = "http://localhost:8000"
STATUS_URL = f"{DASHBOARD_URL}/api/progress"
START_BATCH_URL = f"{DASHBOARD_URL}/api/start-batch"
COMMIT_STATUS_URL = f"{DASHBOARD_URL}/api/commit-progress"

# Asset paths (relative to project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ICON_IDLE = str(PROJECT_ROOT / "assets" / "menubar_icon.png")
ICON_ACTIVE = str(PROJECT_ROOT / "assets" / "menubar_icon_active.png")


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

        self.menu = [
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            rumps.MenuItem("Start Ingestion", callback=self.start_ingestion),
            None,  # separator
            rumps.MenuItem("Status: Idle", callback=None),
            None,  # separator
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        self._status_item = self.menu["Status: Idle"]
        self._is_active = False

        # Start polling timer (every 3 seconds)
        self._timer = rumps.Timer(self._poll_status, 3)
        self._timer.start()

    def open_dashboard(self, _):
        """Open the CoreRag dashboard in the default browser."""
        webbrowser.open(DASHBOARD_URL)

    def start_ingestion(self, _):
        """Trigger batch ingestion via the dashboard API."""
        try:
            import urllib.request

            req = urllib.request.Request(START_BATCH_URL, method="POST")
            with urllib.request.urlopen(req, timeout=5):
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

    def quit_app(self, _):
        """Quit the menu bar app."""
        rumps.quit_application()

    def _poll_status(self, _):
        """Poll the server for ingestion status and update the icon."""
        try:
            import json
            import urllib.request

            # Check batch processing status
            req = urllib.request.Request(STATUS_URL, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())

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
                    req2 = urllib.request.Request(COMMIT_STATUS_URL, method="GET")
                    with urllib.request.urlopen(req2, timeout=2) as resp2:
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
            # Server might not be running — show idle state
            self._status_item.title = "Status: Server unavailable"
            self._set_active(False)

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
