"""Cross-process locking for STEWARD's durable operation journal.

The lock is backed by a persistent sidecar file and an operating-system lock.
The sidecar is never removed: replacing it could let different processes lock
different file objects for the same operation log.
"""

import errno
import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterator, Tuple

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX, not Windows
    msvcrt = None

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows, not POSIX
    fcntl = None


class JournalLockError(RuntimeError):
    """Raised when the operation journal lock cannot be safely acquired."""


class JournalLockTimeoutError(JournalLockError, TimeoutError):
    """Raised when the bounded journal-lock wait expires."""


_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: Dict[str, threading.RLock] = {}
_THREAD_STATE = threading.local()


def _normalized_log_path(operation_log_path: str) -> str:
    return os.path.normcase(os.path.abspath(operation_log_path))


def sidecar_path(operation_log_path: str) -> str:
    """Return the stable sidecar path associated with an operation log."""
    return os.path.abspath(operation_log_path) + ".lock"


def _thread_state() -> Dict[str, Tuple[int, object]]:
    state = getattr(_THREAD_STATE, "locks", None)
    if state is None:
        state = {}
        _THREAD_STATE.locks = state
    return state


def _try_os_lock(handle) -> bool:
    """Try one non-blocking exclusive OS lock; return False on contention."""
    if os.name == "nt":
        if msvcrt is None:
            raise JournalLockError("Windows locking support (msvcrt) is unavailable.")
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise JournalLockError(
                f"Could not lock the operation journal sidecar: {exc}"
            ) from exc
        return True

    if fcntl is None:
        raise JournalLockError("POSIX locking support (fcntl) is unavailable.")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise JournalLockError(
            f"Could not lock the operation journal sidecar: {exc}"
        ) from exc
    return True


def _release_os_lock(handle) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def operation_journal_lock(
    operation_log_path: str,
    timeout: float = 10.0,
) -> Iterator[None]:
    """Serialize journal users across threads and processes.

    The keyed ``RLock`` preserves same-process thread safety. The OS lock
    serializes separate processes. The wait is bounded; timeout or any lock
    API failure raises instead of silently falling back to process-local
    locking.
    """
    if timeout < 0:
        raise ValueError("Journal lock timeout cannot be negative.")

    key = _normalized_log_path(operation_log_path)
    deadline = time.monotonic() + timeout
    state = _thread_state()
    previous = state.get(key)
    if previous is not None:
        depth, handle = previous
        state[key] = (depth + 1, handle)
        try:
            yield
        finally:
            depth, handle = previous
            state[key] = (depth, handle)
        return

    with _LOCKS_GUARD:
        process_lock = _THREAD_LOCKS.setdefault(key, threading.RLock())

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JournalLockTimeoutError(
                f"Timed out after {timeout:g} seconds waiting for the "
                "operation journal lock."
            )
        acquired = process_lock.acquire(timeout=remaining)
        if acquired:
            break

    lock_path = sidecar_path(operation_log_path)
    directory = os.path.dirname(lock_path)
    try:
        os.makedirs(directory, exist_ok=True)
        handle = open(lock_path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
    except OSError as exc:
        process_lock.release()
        raise JournalLockError(
            f"Could not open the operation journal lock sidecar: {exc}"
        ) from exc

    if not handle:
        process_lock.release()
        raise JournalLockError("Could not open the operation journal lock sidecar.")

    acquired = False
    try:
        while True:
            try:
                acquired = _try_os_lock(handle)
            except JournalLockError:
                raise
            except OSError as exc:
                raise JournalLockError(
                    f"Could not lock the operation journal sidecar: {exc}"
                ) from exc
            if acquired:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JournalLockTimeoutError(
                    f"Timed out after {timeout:g} seconds waiting for the "
                    "operation journal lock."
                )
            time.sleep(min(0.05, remaining))

        state[key] = (1, handle)
        try:
            yield
        finally:
            state.pop(key, None)
    finally:
        try:
            if acquired:
                try:
                    _release_os_lock(handle)
                except OSError:
                    # Closing the descriptor also releases an OS-managed lock.
                    pass
        finally:
            handle.close()
            process_lock.release()
