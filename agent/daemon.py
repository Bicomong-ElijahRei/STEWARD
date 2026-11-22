import os
import queue
import time
import threading
from collections import OrderedDict
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
        self._queue = queue.Queue(maxsize=self.MAX_PENDING_FILES)
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"steward-daemon-{index + 1}",
                daemon=True,
            )
            for index in range(self.MAX_WORKERS)
        ]
        for worker in self._workers:
            worker.start()

    @staticmethod
    def _file_identity(filepath):
        """Return a stable identity for the file currently at *filepath*."""
        try:
            stat = os.stat(filepath)
        except OSError:
            return None
        return (stat.st_dev, stat.st_ino)

    def _enqueue_file(self, filepath):
        """Apply backpressure without making the watchdog callback uninterruptible."""
        while not self._stopped.is_set():
            if self._pending_slots.acquire(timeout=0.05):
                break
        else:
            return False
        try:
            self._queue.put_nowait(filepath)
            return True
        except queue.Full:
            self._pending_slots.release()
            return False

    def on_created(self, event):
        if event.is_directory or self._stopped.is_set():
            return
        filepath = event.src_path
        identity = self._file_identity(filepath) or ("missing", filepath)
        with self._lock:
            previous_identity = self.last_processed.get(filepath)
            if previous_identity == identity:
                self.last_processed.move_to_end(filepath)
                return
            self.last_processed[filepath] = identity
            self.last_processed.move_to_end(filepath)
            while len(self.last_processed) > self.MAX_TRACKED_FILES:
                self.last_processed.popitem(last=False)
        if not self._enqueue_file(filepath):
            # A stop raced with backpressure. Remove only this identity so a
            # later restart can reconsider the path if necessary.
            with self._lock:
                if self.last_processed.get(filepath) == identity:
                    self.last_processed.pop(filepath, None)

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

    def _worker_loop(self):
        while not self._stopped.is_set():
            try:
                filepath = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._process_file(filepath)
            finally:
                self._queue.task_done()
                self._pending_slots.release()

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

    def stop(self):
        """Stop accepting work, discard queued files, and release workers."""
        self._stopped.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            else:
                self._queue.task_done()
                self._pending_slots.release()
        for worker in self._workers:
            worker.join(timeout=0.2)
