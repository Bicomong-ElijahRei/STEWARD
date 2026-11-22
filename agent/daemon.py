import os
import time
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from watchdog.events import FileSystemEventHandler


class FileCreationHandler(FileSystemEventHandler):
    """Categorize newly-created files with bounded background concurrency."""

    MAX_TRACKED_FILES = 1000
    MAX_WORKERS = 4
    MAX_PENDING_FILES = 32

    def __init__(self, agent, dest_base, root):
        self.agent = agent
        self.dest_base = dest_base
        self.root = root
        # filepath -> filesystem identity. Keeping the path as the ordered key
        # preserves the existing inspection contract while allowing a file
        # recreated at the same path to be processed again.
        self.last_processed = OrderedDict()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._pending_slots = threading.BoundedSemaphore(self.MAX_PENDING_FILES)
        self._executor = ThreadPoolExecutor(
            max_workers=self.MAX_WORKERS,
            thread_name_prefix="steward-daemon",
        )

    @staticmethod
    def _file_identity(filepath):
        """Return a stable identity for the file currently at *filepath*."""
        try:
            stat = os.stat(filepath)
        except OSError:
            return None
        return (stat.st_dev, stat.st_ino)

    def on_created(self, event):
        if event.is_directory or self._stopped.is_set():
            return
        filepath = event.src_path
        self._pending_slots.acquire()
        if self._stopped.is_set():
            self._pending_slots.release()
            return
        identity = self._file_identity(filepath) or ("missing", filepath)
        with self._lock:
            previous_identity = self.last_processed.get(filepath)
            if previous_identity == identity:
                self.last_processed.move_to_end(filepath)
                self._pending_slots.release()
                return
            self.last_processed[filepath] = identity
            self.last_processed.move_to_end(filepath)
            while len(self.last_processed) > self.MAX_TRACKED_FILES:
                self.last_processed.popitem(last=False)
        try:
            self._executor.submit(self._process_file, filepath)
        except RuntimeError:
            # The handler may have been stopped between the state check and
            # submission. A stopped daemon must not begin new work.
            self._pending_slots.release()
            return

    @staticmethod
    def _wait_until_stable(filepath, timeout=10.0, interval=0.5):
        deadline = time.time() + timeout
        last_size = -1
        while time.time() < deadline:
            try:
                size = os.path.getsize(filepath)
            except OSError:
                return False
            if size == last_size:
                return True
            last_size = size
            time.sleep(interval)
        return False

    def _process_file(self, filepath):
        try:
            if self._stopped.is_set():
                return
            if not self._wait_until_stable(filepath):
                print(f"[Daemon] Skipped (still growing or missing): {filepath}")
                return
            if self._stopped.is_set():
                return
            result = self.agent.categorise_file(
                filepath, self.dest_base, self.root, dry_run=False
            )
            print(f"[Daemon] {result}")
        except Exception as e:
            print(f"[Daemon] Error: {e}")
        finally:
            self._pending_slots.release()

    def stop(self):
        """Stop accepting work and cancel tasks that have not started."""
        self._stopped.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
