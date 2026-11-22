import os
import queue
import time
import threading
from collections import OrderedDict
from datetime import datetime

import schedule
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


class ScheduledScanner:
    """Run a periodic, non-interactive file scan in a background thread."""

    def __init__(
        self,
        file_agent,
        interval_minutes=60,
        incoming_path=None,
        destination_path=None,
        on_scan=None,
    ):
        if isinstance(interval_minutes, bool) or interval_minutes <= 0:
            raise ValueError("interval_minutes must be greater than zero")
        self.file_agent = file_agent
        self.interval = interval_minutes
        self.incoming_path = incoming_path
        self.destination_path = destination_path
        self.on_scan = on_scan
        self._running = False
        self._thread = None
        self._state_lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._scheduler = schedule.Scheduler()
        self.last_scan_time = None
        self.last_error = None
        self.scan_count = 0
        self.files_processed = 0

    @property
    def running(self):
        """Return whether the scheduler thread is active."""
        with self._state_lock:
            return self._running

    def start(self):
        """Start the recurring scan. Returns False when already running."""
        with self._state_lock:
            if self._running:
                return False
            self._scheduler.clear()
            self._scheduler.every(self.interval).minutes.do(self._scan)
            self._running = True
            self._thread = threading.Thread(
                target=self._run_scheduler,
                name="steward-scheduled-scanner",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self):
        """Stop scheduling, wait briefly for the worker, and return its state."""
        with self._state_lock:
            self._running = False
            thread = self._thread
            self._thread = None
        self._scheduler.clear()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        return not self.running

    def _run_scheduler(self):
        while self.running:
            try:
                self._scheduler.run_pending()
            except Exception as exc:
                self.last_error = str(exc)
            time.sleep(0.25)

    def _scan(self):
        """Categorize files currently present in Incoming."""
        if not self._scan_lock.acquire(blocking=False):
            return {
                "processed": 0,
                "failed": 0,
                "skipped": True,
                "error": "scan_already_running",
            }
        try:
            root = os.path.realpath(os.path.abspath(self.file_agent.root_path))
            incoming = os.path.realpath(os.path.abspath(
                self.incoming_path or os.path.join(root, "Incoming")
            ))
            destination = os.path.realpath(os.path.abspath(
                self.destination_path or os.path.join(root, "Sorted")
            ))
            summary = {
                "processed": 0,
                "failed": 0,
                "skipped": False,
                "error": None,
                "files": [],
            }
            if not os.path.isdir(incoming):
                summary["error"] = "incoming_folder_not_found"
                self.last_error = summary["error"]
                self.last_scan_time = datetime.now().isoformat(timespec="seconds")
                self.scan_count += 1
                self._notify_scan(summary)
                return summary

            try:
                filenames = sorted(os.listdir(incoming))
            except OSError as exc:
                summary["error"] = str(exc)
                self.last_error = str(exc)
                self.last_scan_time = datetime.now().isoformat(timespec="seconds")
                self.scan_count += 1
                self._notify_scan(summary)
                return summary

            for filename in filenames:
                filepath = os.path.join(incoming, filename)
                if not os.path.isfile(filepath):
                    continue
                try:
                    result = self.file_agent.categorise_file(
                        filepath, destination, dry_run=False
                    )
                    result_text = str(result or "")
                    moved = not os.path.exists(filepath)
                    if moved and not result_text.startswith("Error"):
                        summary["processed"] += 1
                        self.files_processed += 1
                    else:
                        summary["failed"] += 1
                    summary["files"].append({
                        "filename": filename,
                        "result": result_text,
                        "moved": moved,
                    })
                except Exception as exc:
                    summary["failed"] += 1
                    summary["files"].append({
                        "filename": filename,
                        "result": f"Error: {exc}",
                        "moved": False,
                    })

            self.last_error = summary["error"]
            self.last_scan_time = datetime.now().isoformat(timespec="seconds")
            self.scan_count += 1
            self._notify_scan(summary)
            return summary
        finally:
            self._scan_lock.release()

    def _notify_scan(self, summary):
        if not callable(self.on_scan):
            return
        try:
            self.on_scan(summary)
        except Exception:
            # UI notification failures must not stop future scheduled scans.
            pass
