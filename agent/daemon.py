import os
import queue
import time
import threading
from collections import OrderedDict
from datetime import datetime

import schedule
from watchdog.events import FileSystemEventHandler


DEFAULT_MAX_WATCH_DEPTH = 8
DEFAULT_MAX_WATCHED_DIRECTORIES = 256
DENIED_DIRECTORIES = frozenset({
    ".git", "venv", "__pycache__", "node_modules", "rag_index", "media",
})


class RecursiveScopeRefusal(ValueError):
    """Raised before observer start when recursive coverage exceeds its bounds."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _canonical_directory(path):
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def _path_key(path):
    return os.path.normcase(os.path.abspath(path))


def _is_link_or_junction(path):
    """Return whether a path is a symlink or Windows junction/reparse link."""
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _is_within(path, root):
    try:
        return os.path.commonpath((_path_key(path), _path_key(root))) == _path_key(root)
    except ValueError:
        return False


def build_monitor_scope(
    watch_root,
    destination_roots=(),
    recursive=False,
    max_depth=DEFAULT_MAX_WATCH_DEPTH,
    max_directory_count=DEFAULT_MAX_WATCHED_DIRECTORIES,
):
    """Build a deterministic watcher/scan scope without following links.

    Recursive mode is represented by a set of ordinary directories. Each is
    scheduled separately with ``recursive=False`` so the application, rather
    than the observer library, owns the traversal bound and exclusions.
    """
    root = _canonical_directory(watch_root)
    destinations = tuple(dict.fromkeys(
        _canonical_directory(item) for item in destination_roots if item
    ))
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        raise ValueError("max_depth must be a non-negative integer")
    if (
        isinstance(max_directory_count, bool)
        or not isinstance(max_directory_count, int)
        or max_directory_count < 1
    ):
        raise ValueError("max_directory_count must be a positive integer")
    if not os.path.isdir(root):
        raise RecursiveScopeRefusal("watch_root_not_found", "Watched root does not exist.")
    if _is_link_or_junction(root):
        raise RecursiveScopeRefusal("watch_root_is_link", "Watched root is a link or junction.")
    if any(_is_within(root, item) for item in destinations):
        raise RecursiveScopeRefusal(
            "watch_root_excluded", "Watched root is an excluded destination root."
        )
    if not recursive:
        return {
            "recursive": False,
            "watched_roots": (root,),
            "excluded_roots": destinations,
            "denied_directories": tuple(sorted(DENIED_DIRECTORIES)),
            "bounds": {
                "max_depth": max_depth,
                "max_directory_count": max_directory_count,
            },
            "destination_rule": "flatten",
        }

    watched = []
    pending = [(root, 0)]
    while pending:
        current, depth = pending.pop(0)
        if depth > max_depth:
            raise RecursiveScopeRefusal(
                "depth_limit_exceeded",
                f"Recursive monitoring exceeds maximum depth {max_depth}.",
            )
        if len(watched) >= max_directory_count:
            raise RecursiveScopeRefusal(
                "directory_limit_exceeded",
                "Recursive monitoring exceeds maximum directory count.",
            )
        watched.append(current)
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise RecursiveScopeRefusal(
                "directory_scan_failed", f"Could not inspect '{current}': {exc}"
            ) from exc
        children = []
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            child = os.path.realpath(os.path.abspath(entry.path))
            if _is_link_or_junction(entry.path):
                continue
            if entry.name.casefold() in DENIED_DIRECTORIES:
                continue
            if any(_is_within(child, item) for item in destinations):
                continue
            children.append((child, depth + 1))
        pending.extend(children)
    return {
        "recursive": True,
        "watched_roots": tuple(watched),
        "excluded_roots": destinations,
        "denied_directories": tuple(sorted(DENIED_DIRECTORIES)),
        "bounds": {
            "max_depth": max_depth,
            "max_directory_count": max_directory_count,
        },
        "destination_rule": "flatten",
    }


class DynamicScopeExtender:
    """Extend a recursive scope using the startup scope builder's admission rules."""

    def __init__(
        self,
        scope,
        watch_root,
        destination_roots,
        observer,
        handler,
        max_depth=DEFAULT_MAX_WATCH_DEPTH,
        max_directory_count=DEFAULT_MAX_WATCHED_DIRECTORIES,
        report=None,
    ):
        self.scope = scope
        self.watch_root = watch_root
        self.destination_roots = tuple(destination_roots)
        self.observer = observer
        self.handler = handler
        self.max_depth = max_depth
        self.max_directory_count = max_directory_count
        self.report = report
        self._lock = threading.Lock()

    def _refuse(self, code, message):
        result = {"accepted": False, "code": code, "message": message, "roots": ()}
        if callable(self.report):
            self.report(code, message)
        return result

    def extend(self, directory):
        """Atomically admit and schedule eligible descendants of a new directory."""
        if self.handler._stopped.is_set():
            return self._refuse("daemon_stopped", "Daemon is stopping.")
        if not self.scope.get("recursive"):
            return self._refuse("not_recursive", "Recursive monitoring is disabled.")
        with self._lock:
            if self.handler._stopped.is_set():
                return self._refuse("daemon_stopped", "Daemon is stopping.")
            candidate_path = os.path.abspath(directory)
            if _is_link_or_junction(candidate_path):
                return self._refuse("directory_link_refused", "Directory is a link or junction.")
            candidate = os.path.realpath(candidate_path)
            if not _is_within(candidate, self.watch_root):
                return self._refuse("directory_outside_scope", "Directory is outside the watched scope.")
            if os.path.basename(candidate_path).casefold() == "sorted":
                return self._refuse("directory_excluded", "Sorted directories are excluded.")
            if any(_is_within(candidate, item) for item in self.destination_roots):
                return self._refuse("directory_excluded", "Destination directories are excluded.")
            if os.path.basename(candidate).casefold() in DENIED_DIRECTORIES:
                return self._refuse("directory_excluded", "Denied directory names are excluded.")
            if not os.path.isdir(candidate):
                return self._refuse("directory_not_found", "Directory does not exist.")
            if _is_link_or_junction(candidate):
                return self._refuse("directory_link_refused", "Directory is a link or junction.")
            try:
                rebuilt = build_monitor_scope(
                    self.watch_root,
                    self.destination_roots,
                    recursive=True,
                    max_depth=self.max_depth,
                    max_directory_count=self.max_directory_count,
                )
            except RecursiveScopeRefusal as exc:
                return self._refuse(exc.code, str(exc))
            existing = tuple(self.scope.get("watched_roots", ()))
            existing_keys = {_path_key(item) for item in existing}
            additions = tuple(
                item for item in rebuilt["watched_roots"]
                if _path_key(item) not in existing_keys
            )
            if not additions:
                return {"accepted": False, "code": "already_watched", "message": "Directory is already watched.", "roots": ()}
            if len(existing) + len(additions) > self.max_directory_count:
                return self._refuse(
                    "directory_limit_exceeded",
                    f"Recursive monitoring exceeds maximum directory count {self.max_directory_count}.",
                )
            for watched_root in additions:
                if self.handler._stopped.is_set():
                    return self._refuse("daemon_stopped", "Daemon is stopping.")
                self.observer.schedule(self.handler, watched_root, recursive=False)
            self.scope["watched_roots"] = existing + additions
            result = {
                "accepted": True,
                "code": "scope_extended",
                "message": "Recursive monitoring scope extended.",
                "roots": additions,
            }
            if callable(self.report):
                self.report("scope_extended", f"Watching new recursive roots: {additions}")
            return result


class FileCreationHandler(FileSystemEventHandler):
    """Categorize newly-created files with bounded background concurrency."""

    MAX_TRACKED_FILES = 1000
    MAX_WORKERS = 4
    MAX_PENDING_FILES = 32

    def __init__(self, agent, dest_base, root, scope=None):
        self.agent = agent
        self.dest_base = dest_base
        self.root = root
        self.scope = scope
        self.directory_callback = None
        # filepath -> filesystem identity. Keeping the path as the ordered key
        # preserves the existing inspection contract while allowing a file
        # recreated at the same path to be processed again.
        self.last_processed = OrderedDict()
        self._in_flight = set()
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

    def _path_in_scope(self, filepath):
        if not self.scope:
            return True
        canonical = os.path.realpath(os.path.abspath(filepath))
        excluded = self.scope.get("excluded_roots", ())
        if any(_is_within(canonical, item) for item in excluded):
            return False
        watched = self.scope.get("watched_roots", ())
        return any(_is_within(canonical, item) for item in watched)

    def on_created(self, event):
        if self._stopped.is_set():
            return False
        if event.is_directory:
            if self.scope and self.scope.get("recursive") and callable(self.directory_callback):
                result = self.directory_callback(event.src_path)
                return bool(result and result.get("accepted"))
            return False
        filepath = event.src_path
        if not self._path_in_scope(filepath):
            return False
        identity = self._file_identity(filepath) or ("missing", filepath)
        with self._lock:
            previous_identity = self.last_processed.get(filepath)
            if previous_identity == identity:
                self.last_processed.move_to_end(filepath)
                return False
            if len(self.last_processed) >= self.MAX_TRACKED_FILES:
                evictable = next(
                    (
                        path for path in self.last_processed
                        if path not in self._in_flight
                    ),
                    None,
                )
                if evictable is None:
                    return False
                self.last_processed.pop(evictable, None)
            self.last_processed[filepath] = identity
            self.last_processed.move_to_end(filepath)
            self._in_flight.add(filepath)
        if not self._enqueue_file(filepath):
            # A stop raced with backpressure. Remove only this identity so a
            # later restart can reconsider the path if necessary.
            with self._lock:
                self._in_flight.discard(filepath)
                if self.last_processed.get(filepath) == identity:
                    self.last_processed.pop(filepath, None)
            return False
        return True

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
                with self._lock:
                    self._in_flight.discard(filepath)
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
        stop_timeout=5.0,
        recursive=False,
        max_depth=DEFAULT_MAX_WATCH_DEPTH,
        max_directory_count=DEFAULT_MAX_WATCHED_DIRECTORIES,
    ):
        if isinstance(interval_minutes, bool) or interval_minutes <= 0:
            raise ValueError("interval_minutes must be greater than zero")
        self.file_agent = file_agent
        self.interval = interval_minutes
        self.incoming_path = incoming_path
        self.destination_path = destination_path
        self.on_scan = on_scan
        self.recursive = recursive
        self.max_depth = max_depth
        self.max_directory_count = max_directory_count
        self.stop_timeout = float(stop_timeout)
        if self.stop_timeout < 0:
            raise ValueError("stop_timeout must be non-negative")
        self._running = False
        self._thread = None
        self._state_lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._scheduler = schedule.Scheduler()
        self._generation = 0
        self._cancel_event = None
        self._active_scans = 0
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
            # A previous scheduler thread may still be winding down after
            # stop(), and a previous scan may still be unwinding. Starting a
            # new generation is safe because the scan mutex serializes scan
            # bodies, while generation/event ownership prevents the old worker
            # from committing into the new state.
            self._generation += 1
            generation = self._generation
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            self._scheduler.clear()
            self._scheduler.every(self.interval).minutes.do(
                self._scan, cancel_event, generation
            )
            self._running = True
            self._thread = threading.Thread(
                target=self._run_scheduler,
                args=(cancel_event, generation),
                name="steward-scheduled-scanner",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self):
        """Stop scheduling, wait briefly for the worker, and return its state."""
        with self._state_lock:
            # Cancellation and commit ownership share this lock. Setting the
            # event before releasing it makes stop linearize against a scan's
            # commit boundary: a commit that acquired the lock first is a
            # completed scan; a commit that acquires it afterwards is
            # cancelled and cannot publish state.
            cancel_event = self._cancel_event
            if cancel_event is not None:
                cancel_event.set()
            self._running = False
            thread = self._thread
        self._scheduler.clear()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.stop_timeout)
        with self._state_lock:
            worker_alive = thread is not None and thread.is_alive()
            scan_alive = self._active_scans > 0
            if not worker_alive and thread is self._thread:
                self._thread = None
            return not worker_alive and not scan_alive

    def _run_scheduler(self, cancel_event, generation):
        while not cancel_event.is_set():
            with self._state_lock:
                if generation != self._generation or self._cancel_event is not cancel_event:
                    return
            try:
                self._scheduler.run_pending()
            except Exception as exc:
                self.last_error = str(exc)
            cancel_event.wait(0.25)

    def _monitor_scope(self):
        """Return the same bounded scope contract used by the watcher."""
        root = os.path.realpath(os.path.abspath(self.file_agent.root_path))
        incoming = os.path.realpath(os.path.abspath(
            self.incoming_path or os.path.join(root, "Incoming")
        ))
        destination = os.path.realpath(os.path.abspath(
            self.destination_path or os.path.join(root, "Sorted")
        ))
        sorted_root = os.path.realpath(os.path.abspath(os.path.join(root, "Sorted")))
        return build_monitor_scope(
            incoming,
            [sorted_root, destination],
            recursive=self.recursive,
            max_depth=self.max_depth,
            max_directory_count=self.max_directory_count,
        )

    def _scan(self, cancel_event=None, generation=None):
        """Categorize files currently present in Incoming."""
        with self._state_lock:
            if cancel_event is None:
                cancel_event = self._cancel_event or threading.Event()
            if generation is None:
                generation = self._generation
            current = generation == self._generation
        if not current:
            return self._skipped_scan("stale_generation", cancelled=False)
        if cancel_event.is_set():
            return self._skipped_scan("scan_cancelled", cancelled=True)

        if not self._scan_lock.acquire(blocking=False):
            return self._skipped_scan("scan_already_running", cancelled=False)
        with self._state_lock:
            if generation != self._generation:
                current = False
            elif cancel_event.is_set():
                current = False
            else:
                self._active_scans += 1
        if not current:
            self._scan_lock.release()
            if cancel_event.is_set():
                return self._skipped_scan("scan_cancelled", cancelled=True)
            return self._skipped_scan("stale_generation", cancelled=False)

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
                "cancelled": False,
            }
            if not os.path.isdir(incoming):
                summary["error"] = "incoming_folder_not_found"
                self._commit_scan(summary, generation, cancel_event)
                return summary

            try:
                scope = self._monitor_scope()
            except RecursiveScopeRefusal as exc:
                summary["error"] = exc.code
                self._commit_scan(summary, generation, cancel_event)
                return summary
            files = []
            for watched_root in scope["watched_roots"]:
                try:
                    filenames = sorted(os.listdir(watched_root))
                except OSError as exc:
                    summary["error"] = str(exc)
                    self._commit_scan(summary, generation, cancel_event)
                    return summary
                for filename in filenames:
                    files.append(os.path.join(watched_root, filename))

            for filepath in files:
                if cancel_event.is_set():
                    summary["cancelled"] = True
                    summary["error"] = "scan_cancelled"
                    break
                with self._state_lock:
                    if generation != self._generation:
                        summary["skipped"] = True
                        summary["error"] = "stale_generation"
                        return summary
                filename = os.path.basename(filepath)
                if not os.path.isfile(filepath) or _is_link_or_junction(filepath):
                    continue
                try:
                    result = self.file_agent.categorise_file(
                        filepath, destination, dry_run=False
                    )
                    result_text = str(result or "")
                    moved = not os.path.exists(filepath)
                    if moved and not result_text.startswith("Error"):
                        summary["processed"] += 1
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
                if cancel_event.is_set():
                    summary["cancelled"] = True
                    summary["error"] = "scan_cancelled"
                    break

            self._commit_scan(summary, generation, cancel_event)
            return summary
        finally:
            with self._state_lock:
                self._active_scans -= 1
            self._scan_lock.release()

    @staticmethod
    def _skipped_scan(error, cancelled=False):
        """Build a summary for a scan rejected before it owns any work."""
        return {
            "processed": 0,
            "failed": 0,
            "skipped": True,
            "error": error,
            "files": [],
            "cancelled": cancelled,
        }

    def _commit_scan(self, summary, generation, cancel_event):
        """Atomically commit and notify state for the owning generation.

        The generation and cancellation event are both part of the commit
        token.  This prevents a cancelled or superseded worker from publishing
        state after its ownership has ended.
        """
        with self._state_lock:
            if generation != self._generation:
                summary["skipped"] = True
                summary["error"] = "stale_generation"
                return False
            if (
                cancel_event is None
                or cancel_event.is_set()
                or (
                    self._cancel_event is not None
                    and cancel_event is not self._cancel_event
                )
            ):
                summary["skipped"] = True
                summary["cancelled"] = True
                summary["error"] = "scan_cancelled"
                return False
            self.last_error = summary["error"]
            self.last_scan_time = datetime.now().isoformat(timespec="seconds")
            self.scan_count += 1
            self.files_processed += summary["processed"]
            self._notify_scan(summary)
        return True

    def _notify_scan(self, summary):
        if not callable(self.on_scan):
            return
        try:
            self.on_scan(summary)
        except Exception:
            # UI notification failures must not stop future scheduled scans.
            pass
