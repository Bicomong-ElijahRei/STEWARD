"""C4-I1 pure bounded iteration controller.

The controller coordinates one bounded healing loop through injected
interfaces only. It never starts an operating-system process, never invokes
dynamic code, and never applies a patch. The executor is an injected object;
in this batch only test fakes implement it, and C4 remains BACKLOG.

Durability contract
-------------------
The controller writes a write-ahead journal through an injected journal
object. The required order per iteration is an ``intent`` record before the
executor call and an ``outcome`` record after it, followed by one
``terminal`` record for the run. This mirrors the durable intent/outcome
pattern used by ``agents.file_agent.FileAgent`` (see ``_begin_mutation``,
``_complete_mutation`` and the atomic save in ``_save_operation_log_locked``)
and the cross-process ordering in ``agent.journal_lock``. The journal object
owns durable publication details; this module owns only the ordering and the
record content. Records carry metadata and bounded, redacted observation
text: never source content and never unbounded output.

Approval boundary
-----------------
The controller may request a proposal through an injected callback. It has no
apply path: C3's single-use exact-diff approval remains the only route from
a proposal to a file change.

Bounds
------
The controller owns the hard iteration bound, the optional per-iteration and
total wall-clock bounds, the observation bounds, and every termination
decision; the injected executor cannot extend or reset any of them. The
wall-clock bounds are measured with an injectable clock so tests stay
deterministic. Because this controller never runs a process, it can only
detect an elapsed timeout after the executor returns: interrupting a running
child mid-call remains the future executor's responsibility under the
operating-system isolation required by ``docs/self_healing_review.md``.
"""

from dataclasses import dataclass
import hashlib
import re
import time
from typing import Any, Dict, Optional, Protocol, Tuple


STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
STATUS_UNRECOVERABLE_ERROR = "unrecoverable_error"
STATUS_CANCELLED = "cancelled"
STATUS_BOUND_REACHED = "bound_reached"
STATUS_REPEATED_FAILURE = "repeated_failure"
STATUS_JOURNAL_ERROR = "journal_error"
STATUS_UNCERTAIN = "uncertain"
STATUS_TIMEOUT = "timeout"

_EXECUTOR_STATUSES = frozenset({
    STATUS_SUCCESS,
    STATUS_FAILURE,
    STATUS_UNRECOVERABLE_ERROR,
    STATUS_CANCELLED,
})

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\b(\s*[:=]\s*)(\S+)"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)


@dataclass(frozen=True)
class ExecutorRequest:
    """Metadata handed to the injected executor for one iteration."""

    iteration: int
    run_id: Optional[str] = None


@dataclass(frozen=True)
class ExecutorResult:
    """Typed, untrusted observation returned by an injected executor."""

    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    failure_code: str = ""


@dataclass(frozen=True)
class ProposalRequest:
    """A request to enter the existing C3 proposal gate, never to apply."""

    iteration: int
    observation: Dict[str, Any]
    failure_code: str = ""


@dataclass(frozen=True)
class ControllerResult:
    """Terminal state of one controller run."""

    status: str
    iterations_completed: int
    detail: str = ""


class Journal(Protocol):
    """Durable journal contract used by the controller."""

    def write(self, record: Dict[str, Any]) -> None:
        """Durably publish one metadata record."""


def _redact(text: str) -> Tuple[str, int]:
    """Replace secret-looking values deterministically; return text and count."""

    count = 0

    def _assignment(match):
        nonlocal count
        count += 1
        return "{}{}{}".format(match.group(1), match.group(2), "[REDACTED]")

    def _block(_match):
        nonlocal count
        count += 1
        return "[REDACTED_PRIVATE_KEY]"

    redacted = _SECRET_ASSIGNMENT.sub(_assignment, text)
    redacted = _PRIVATE_KEY_BLOCK.sub(_block, redacted)
    return redacted, count


def _bound_text(text: str, limit: int) -> Tuple[str, bool, int]:
    """Return bounded text, a truncation flag, and the original length."""

    original = len(text)
    if original <= limit:
        return text, False, original
    return text[:limit], True, original


class HealingController:
    """Bounded, deterministic iteration controller over injected interfaces.

    The controller owns the hard iteration bound, the write-ahead ordering,
    observation bounds, and every termination decision. The injected executor
    owns no authority: it may only return an observation.
    """

    def __init__(
        self,
        executor,
        journal,
        proposal_callback=None,
        is_cancelled=None,
        max_iterations=3,
        max_observation_chars=4096,
        repeated_failure_limit=2,
        iteration_timeout_seconds=None,
        total_timeout_seconds=None,
        clock=None,
        run_id="healing-run",
    ):
        if not callable(getattr(executor, "execute", None)):
            raise TypeError("executor must provide an execute(request) method")
        if not callable(getattr(journal, "write", None)):
            raise TypeError("journal must provide a write(record) method")
        if proposal_callback is not None and not callable(proposal_callback):
            raise TypeError("proposal_callback must be callable")
        if is_cancelled is not None and not callable(is_cancelled):
            raise TypeError("is_cancelled must be callable")
        if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
            raise TypeError("max_iterations must be an integer")
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if not isinstance(max_observation_chars, int) or isinstance(max_observation_chars, bool):
            raise TypeError("max_observation_chars must be an integer")
        if max_observation_chars < 0:
            raise ValueError("max_observation_chars must not be negative")
        if not isinstance(repeated_failure_limit, int) or isinstance(repeated_failure_limit, bool):
            raise TypeError("repeated_failure_limit must be an integer")
        if repeated_failure_limit < 1:
            raise ValueError("repeated_failure_limit must be at least 1")
        if iteration_timeout_seconds is not None and iteration_timeout_seconds <= 0:
            raise ValueError("iteration_timeout_seconds must be positive")
        if total_timeout_seconds is not None and total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        self.executor = executor
        self.journal = journal
        self.proposal_callback = proposal_callback
        self.is_cancelled = is_cancelled
        self.max_iterations = max_iterations
        self.max_observation_chars = max_observation_chars
        self.repeated_failure_limit = repeated_failure_limit
        self.iteration_timeout_seconds = iteration_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.clock = clock if clock is not None else time.monotonic
        self.run_id = run_id

    # -- journal helpers -------------------------------------------------

    def _write(self, record):
        self.journal.write(record)

    def _intent_record(self, iteration):
        return {
            "run_id": self.run_id,
            "iteration": iteration,
            "phase": "intent",
            "status": "started",
        }

    def _outcome_record(self, iteration, outcome, observation):
        return {
            "run_id": self.run_id,
            "iteration": iteration,
            "phase": "outcome",
            "status": outcome.status,
            "failure_code": outcome.failure_code,
            "exit_code": outcome.exit_code,
            "observation": observation,
        }

    def _terminal_record(self, status, iterations_completed):
        return {
            "run_id": self.run_id,
            "iteration": iterations_completed,
            "iterations_completed": iterations_completed,
            "phase": "terminal",
            "status": status,
        }

    # -- observation helpers ---------------------------------------------

    def _bound_stream(self, text):
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        original = len(text)
        redacted, redactions = _redact(text)
        bounded, truncated, _ = _bound_text(redacted, self.max_observation_chars)
        return {
            "text": bounded,
            "truncated": truncated,
            "original_chars": original,
            "redactions": redactions,
        }

    def _observation(self, outcome):
        return {
            "stdout": self._bound_stream(outcome.stdout),
            "stderr": self._bound_stream(outcome.stderr),
        }

    def _failure_signature(self, outcome, observation):
        payload = "\x1f".join([
            outcome.status,
            outcome.failure_code or "",
            observation["stdout"]["text"],
            observation["stderr"]["text"],
        ])
        return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()

    def _finish(self, status, iterations_completed, detail):
        self._write(self._terminal_record(status, iterations_completed))
        return ControllerResult(
            status=status,
            iterations_completed=iterations_completed,
            detail=detail,
        )

    # -- loop -------------------------------------------------------------

    def run(self):
        """Run the bounded loop and return a truthful terminal result."""

        iteration = 0
        iterations_completed = 0
        last_signature = None
        repeated_count = 0
        started_at = self.clock()

        while True:
            if self.is_cancelled is not None and self.is_cancelled():
                return self._finish(
                    STATUS_CANCELLED,
                    iterations_completed,
                    "cancelled before iteration {}".format(iteration + 1),
                )

            if iteration >= self.max_iterations:
                return self._finish(
                    STATUS_BOUND_REACHED,
                    iterations_completed,
                    "hard iteration bound of {} reached".format(self.max_iterations),
                )

            if self.total_timeout_seconds is not None:
                if self.clock() - started_at >= self.total_timeout_seconds:
                    return self._finish(
                        STATUS_TIMEOUT,
                        iterations_completed,
                        "total wall-clock bound of {}s reached".format(
                            self.total_timeout_seconds
                        ),
                    )

            iteration += 1

            try:
                self._write(self._intent_record(iteration))
            except Exception as exc:
                return ControllerResult(
                    status=STATUS_JOURNAL_ERROR,
                    iterations_completed=iterations_completed,
                    detail="journal intent write failed: {}".format(type(exc).__name__),
                )

            request = ExecutorRequest(iteration=iteration, run_id=self.run_id)
            iteration_started_at = self.clock()
            try:
                raw = self.executor.execute(request)
            except Exception as exc:
                outcome = ExecutorResult(
                    status=STATUS_UNRECOVERABLE_ERROR,
                    stderr=str(exc),
                    failure_code=type(exc).__name__,
                )
            else:
                if not isinstance(raw, ExecutorResult):
                    outcome = ExecutorResult(
                        status=STATUS_UNRECOVERABLE_ERROR,
                        stderr="executor returned an unsupported result type",
                        failure_code="invalid_result",
                    )
                elif raw.status not in _EXECUTOR_STATUSES:
                    outcome = ExecutorResult(
                        status=STATUS_UNRECOVERABLE_ERROR,
                        stdout=raw.stdout,
                        stderr=raw.stderr,
                        exit_code=raw.exit_code,
                        failure_code="invalid_status",
                    )
                else:
                    outcome = raw

            observation = self._observation(outcome)

            if self.iteration_timeout_seconds is not None:
                if self.clock() - iteration_started_at >= self.iteration_timeout_seconds:
                    outcome = ExecutorResult(
                        status=STATUS_TIMEOUT,
                        stdout=outcome.stdout,
                        stderr=outcome.stderr,
                        exit_code=outcome.exit_code,
                        failure_code="iteration_timeout",
                    )
                    observation = self._observation(outcome)

            try:
                self._write(self._outcome_record(iteration, outcome, observation))
            except Exception as exc:
                return ControllerResult(
                    status=STATUS_UNCERTAIN,
                    iterations_completed=iterations_completed,
                    detail="journal outcome write failed: {}".format(type(exc).__name__),
                )

            iterations_completed = iteration

            if outcome.status == STATUS_SUCCESS:
                return self._finish(
                    STATUS_SUCCESS, iterations_completed, "success signal received"
                )

            if outcome.status in (
                STATUS_UNRECOVERABLE_ERROR,
                STATUS_CANCELLED,
                STATUS_TIMEOUT,
            ):
                return self._finish(
                    outcome.status,
                    iterations_completed,
                    outcome.failure_code or outcome.status,
                )

            signature = self._failure_signature(outcome, observation)
            if signature == last_signature:
                repeated_count += 1
            else:
                repeated_count = 1
                last_signature = signature

            if repeated_count >= self.repeated_failure_limit:
                return self._finish(
                    STATUS_REPEATED_FAILURE,
                    iterations_completed,
                    "repeated identical failure {} time(s)".format(repeated_count),
                )

            if self.proposal_callback is not None:
                proposal_request = ProposalRequest(
                    iteration=iteration,
                    observation=observation,
                    failure_code=outcome.failure_code,
                )
                try:
                    self.proposal_callback(proposal_request)
                except Exception as exc:
                    return self._finish(
                        STATUS_UNRECOVERABLE_ERROR,
                        iterations_completed,
                        "proposal callback failed: {}".format(type(exc).__name__),
                    )
