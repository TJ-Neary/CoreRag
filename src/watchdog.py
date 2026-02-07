import asyncio
import logging
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.config import INBOX_PATH
from src.utils.logging_config import setup_logging

# Configure logging (centralized: colored console, rotating file, JSON, error-only)
setup_logging()
logger = logging.getLogger(__name__)


class IngestionHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        # Using a small delay to ensure file copy is complete
        time.sleep(1)
        self.handle_file(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self.handle_file(event.dest_path)

    def handle_file(self, file_path_str):
        file_path = Path(file_path_str)
        # Ignore hidden files (like .DS_Store)
        if file_path.name.startswith("."):
            return

        logger.info(f"Detected file: {file_path.name}")

        try:
            # We will import this dynamically to avoid circular imports if any
            from src.processor import process_document

            asyncio.run(process_document(file_path))
        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}")


def start_watchdog():
    if not INBOX_PATH or not INBOX_PATH.exists():
        logger.error(f"Inbox path invalid or does not exist: {INBOX_PATH}")
        sys.exit(1)

    event_handler = IngestionHandler()
    observer = Observer()
    observer.schedule(event_handler, str(INBOX_PATH), recursive=False)
    observer.start()
    logger.info(f"Started Watching Inbox: {INBOX_PATH}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("Stopping Watchdog...")

    observer.join()


if __name__ == "__main__":
    start_watchdog()
