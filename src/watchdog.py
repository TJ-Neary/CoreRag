import time
import sys
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from src.config import INBOX_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

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
        if file_path.name.startswith('.'):
            return

        logging.info(f"Detected file: {file_path.name}")

        try:
            # We will import this dynamically to avoid circular imports if any
            from src.processor import process_document
            process_document(file_path)
        except Exception as e:
            logging.error(f"Failed to process {file_path.name}: {e}")

def start_watchdog():
    if not INBOX_PATH or not INBOX_PATH.exists():
        logging.error(f"Inbox path invalid or does not exist: {INBOX_PATH}")
        sys.exit(1)

    event_handler = IngestionHandler()
    observer = Observer()
    observer.schedule(event_handler, str(INBOX_PATH), recursive=False)
    observer.start()
    logging.info(f"Started Watching Inbox: {INBOX_PATH}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Stopping Watchdog...")

    observer.join()

if __name__ == "__main__":
    start_watchdog()
