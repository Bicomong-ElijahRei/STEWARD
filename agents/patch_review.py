"""C3 proposal, immutable artifact, distinct approval, and recovery facade."""

import base64
import copy
import hashlib
import json
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone

from agent.journal_lock import JournalLockError, operation_journal_lock
from agents.patch_applier import (
    PatchAdmissionError,
    PatchApplyError,
    PatchApplier,
    PatchRecoveryError,
)
from agents.patch_engine import (
    PatchEngineError,
    decode_patch_artifact,
    materialize_proposal,
)
from core.database import APP_DATA_DIR


PATCH_REFUSAL_ERROR = "Patch request was refused."
MAX_PROVIDER_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024
MAX_SOURCE_CONTEXT_CHARS = 16000
MAX_INTENT_CHARS = 4000
MAX_TARGETS = 1000
_TOOL_MARKERS = (
    '"tool_calls"', '"tool_call"', '"function_call"', '"recipient_name"',
)


class PatchRefusal(RuntimeError):
    """Raised with one uniform contract for every refused patch action."""


def _refuse(detail=""):
    raise PatchRefusal(PATCH_REFUSAL_ERROR)


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty JSON response")
    if len(text.encode("utf-8")) > MAX_PROVIDER_BYTES:
        raise ValueError("Provider response is oversized")
    lowered = text.casefold()
    if any(marker in lowered for marker in _TOOL_MARKERS):
        raise ValueError("Provider response contains a tool call")
    return json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Forbidden JSON constant: {value}")
        ),
    )


PROPOSAL_PROMPT = """You are Syntax, STEWARD's text-only patch proposer.
Return one strict JSON object only. No Markdown, tools, filesystem access, or
runtime actions. The exact schema is:
{"relative_path":"relative/path.py","edits":[{"op":"replace_node","anchor":{"node_kind":"FunctionDef","qualified_name":"Module.name","occurrence":0},"replacement":"replacement source text"}]}
Use one relative path only. Allowed ops are replace_node, insert_before, and
insert_after. The anchor must identify one existing function or class. Return
only the requested relative path and structural edit intent."""


class PatchReviewManager:
    """Own proposal, immutable artifacts, C3 approval, apply, and recovery."""

    def __init__(
        self,
        api_manager,
        plan_agent,
        incoming_root,
        sorted_root,
        patches_dir=None,
        backup_root=None,
        operation_log_path=None,
    ):
        self.api_manager = api_manager
        self.plan_agent = plan_agent
        self.incoming_root = incoming_root
        self.sorted_root = sorted_root
        self.patches_dir = os.path.abspath(
            patches_dir or os.path.join(APP_DATA_DIR, "patches")
        )
        self.backup_root = os.path.abspath(
            backup_root or os.path.join(APP_DATA_DIR, "c3_backups")
        )
        self.operation_log_path = operation_log_path
        self._lock = threading.RLock()
        self._pending = None
        self._approval = None
        self._consumed_approval_ids = set()
        self._approved_patch_ids = set()
        self._apply_in_progress = False
        self._cancel_requested = threading.Event()
        self._last_workspace_root = None
        self._conversation_epoch = None

    def _applier(self, workspace_root):
        try:
            return PatchApplier(
                workspace_root=workspace_root,
                incoming_root=self.incoming_root,
                sorted_root=self.sorted_root,
                operation_log_path=self.operation_log_path,
                backup_root=self.backup_root,
            )
        except (PatchAdmissionError, OSError):
            _refuse()

    def list_targets(self, workspace_root):
        """Return admitted Python targets for the explicit workspace picker."""
        applier = self._applier(workspace_root)
        targets = []
        for directory, names, files in os.walk(applier.workspace.canonical_root):
            names[:] = sorted(name for name in names if name != "__pycache__")
            for name in sorted(files):
                if not name.lower().endswith(".py"):
                    continue
                relative = os.path.relpath(
                    os.path.join(directory, name), applier.workspace.canonical_root
                ).replace(os.sep, "/")
                try:
                    applier.admit_target(relative)
                except PatchAdmissionError:
                    continue
                targets.append(relative)
                if len(targets) >= MAX_TARGETS:
                    return targets
        return targets

    def propose(
        self,
        workspace_root,
        relative_path,
        intent,
        plan_id,
        conversation_epoch=None,
        is_current=None,
        epoch=None,
    ):
        """Request, validate, materialize, and persist one bounded proposal."""
        if conversation_epoch is None:
            conversation_epoch = epoch
        if not isinstance(intent, str) or not intent.strip():
            _refuse()
        if len(intent) > MAX_INTENT_CHARS:
            _refuse()
        if isinstance(conversation_epoch, bool) or not isinstance(conversation_epoch, int):
            _refuse()
        if not isinstance(plan_id, str) or not plan_id:
            _refuse()
        with self._lock:
            # A new proposal may supersede an unapproved preview.  An approved
            # proposal remains protected until it is applied or explicitly
            # cancelled/declined; replacing it would strand a valid approval.
            if self._pending is not None and self._approval is not None:
                _refuse()
            if (
                self._conversation_epoch is not None
                and conversation_epoch != self._conversation_epoch
            ):
                _refuse()
            if is_current is not None and not is_current():
                _refuse()
        if not self.plan_agent.is_reviewed_plan(plan_id):
            _refuse()
        if conversation_epoch is None:
            _refuse()
        applier = self._applier(workspace_root)
        try:
            admitted = applier.admit_target(relative_path)
            with open(admitted.canonical_path, "rb") as handle:
                source_bytes = handle.read()
        except (PatchAdmissionError, OSError):
            _refuse()
        try:
            source_text = source_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _refuse()
        context = source_text[:MAX_SOURCE_CONTEXT_CHARS]
        if len(source_text) > MAX_SOURCE_CONTEXT_CHARS:
            context += "\n# SOURCE TRUNCATED FOR BOUNDED PROPOSAL"
        request = {
            "agent_name": "Syntax",
            "required_tier": "Tier 1",
            "require_tools": False,
            "messages": [
                {"role": "system", "content": PROPOSAL_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"relative_path: {relative_path}\n"
                        f"intent: {intent}\nsource:\n{context}"
                    ),
                },
            ],
        }
        try:
            response = self.api_manager.route_request(**request)
        except Exception:
            _refuse()
        if is_current is not None and not is_current():
            _refuse()
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            _refuse()
        if not isinstance(message, dict) or message.get("tool_calls"):
            _refuse()
        content = message.get("content")
        if not isinstance(content, str):
            _refuse()
        try:
            proposal = _decode_json(content)
        except (TypeError, ValueError, UnicodeError):
            _refuse()
        if not isinstance(proposal, dict):
            _refuse()
        if proposal.get("relative_path") != relative_path:
            _refuse()
        patch_id = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            patch, encoded = materialize_proposal(
                source_bytes,
                proposal,
                patch_id,
                plan_id,
                applier.workspace.fingerprint,
                created,
            )
        except (PatchEngineError, UnicodeError):
            _refuse()
        try:
            staged = applier.stage(patch, encoded)
        except PatchApplyError:
            _refuse()
        diff_bytes = staged.unified_diff
        output_sha256 = _sha256(staged.output_bytes)
        source_sha256 = _sha256(source_bytes)
        artifact = {
            "schema_version": 1,
            "patch_id": patch_id,
            "plan_id": plan_id,
            "conversation_epoch": conversation_epoch,
            "workspace_fingerprint": applier.workspace.fingerprint,
            "relative_paths": [relative_path],
            "source_hashes": [source_sha256],
            "output_hashes": [output_sha256],
            "source_sha256": source_sha256,
            "output_sha256": output_sha256,
            "diff_sha256": _sha256(diff_bytes),
            "unified_diff_base64": base64.b64encode(diff_bytes).decode("ascii"),
            "patch": patch,
            "patch_base64": base64.b64encode(encoded).decode("ascii"),
            "created_utc": created,
        }
        artifact_bytes = json.dumps(
            artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if len(artifact_bytes) > MAX_ARTIFACT_BYTES:
            _refuse()
        artifact_sha256 = _sha256(artifact_bytes)
        artifact_path = os.path.join(self.patches_dir, f"{patch_id}.json")
        self._write_once(artifact_path, artifact_bytes)
        if is_current is not None and not is_current():
            _refuse()
        with self._lock:
            if is_current is not None and not is_current():
                _refuse()
            # Re-check the protected-state invariant after the slow provider
            # and artifact-persistence phases.  A concurrent approval must not
            # be stranded by a proposal that started before that approval.
            if self._approval is not None:
                _refuse()
            self._conversation_epoch = conversation_epoch
            self._pending = {
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha256,
                "artifact": artifact,
                "patch": patch,
                "encoded_patch": encoded,
                "diff_bytes": diff_bytes,
                "diff_sha256": _sha256(diff_bytes),
                "output_sha256": output_sha256,
                "source_sha256": source_sha256,
                "workspace_fingerprint": applier.workspace.fingerprint,
                "plan_id": plan_id,
                "conversation_epoch": conversation_epoch,
                "workspace_root": os.path.abspath(workspace_root),
                "staged": staged,
            }
        return {
            "patch_id": patch_id,
            "artifact_sha256": artifact_sha256,
            "artifact_path": artifact_path,
            "plan_id": plan_id,
            "conversation_epoch": conversation_epoch,
            "workspace_fingerprint": applier.workspace.fingerprint,
            "relative_paths": [relative_path],
            "source_hashes": [source_sha256],
            "output_hashes": [output_sha256],
            "source_sha256": source_sha256,
            "output_sha256": output_sha256,
            "diff_bytes": diff_bytes,
            "diff_sha256": _sha256(diff_bytes),
        }

    def _write_once(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            _refuse()
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise

    def _verify_artifact(self, pending):
        """Re-read the write-once artifact and verify every immutable binding."""
        try:
            with open(pending["artifact_path"], "rb") as handle:
                artifact_bytes = handle.read()
        except OSError:
            _refuse()
        if _sha256(artifact_bytes) != pending["artifact_sha256"]:
            _refuse()
        try:
            artifact = json.loads(artifact_bytes.decode("utf-8"))
        except (UnicodeError, ValueError):
            _refuse()
        if artifact != pending["artifact"]:
            _refuse()
        expected = pending["artifact"]
        if artifact.get("patch_id") != expected.get("patch_id"):
            _refuse()
        if artifact.get("plan_id") != expected.get("plan_id"):
            _refuse()
        if artifact.get("workspace_fingerprint") != expected.get("workspace_fingerprint"):
            _refuse()
        if artifact.get("relative_paths") != expected.get("relative_paths"):
            _refuse()
        if artifact.get("source_hashes") != pending["artifact"]["source_hashes"]:
            _refuse()
        if artifact.get("output_hashes") != pending["artifact"]["output_hashes"]:
            _refuse()
        if artifact.get("source_sha256") != pending["source_sha256"]:
            _refuse()
        if artifact.get("output_sha256") != pending["output_sha256"]:
            _refuse()
        if artifact.get("diff_sha256") != pending["diff_sha256"]:
            _refuse()
        try:
            encoded = base64.b64decode(
                artifact["patch_base64"], validate=True
            )
            diff_bytes = base64.b64decode(
                artifact["unified_diff_base64"], validate=True
            )
            decoded = decode_patch_artifact(encoded)
        except (KeyError, ValueError, TypeError, PatchEngineError):
            _refuse()
        if encoded != pending["encoded_patch"] or diff_bytes != pending["diff_bytes"]:
            _refuse()
        if decoded != pending["patch"]:
            _refuse()
        return encoded, diff_bytes

    def approve(self, patch_id, conversation_epoch=None, epoch=None):
        """Approve exactly one artifact with a distinct single-use token."""
        if conversation_epoch is None:
            conversation_epoch = epoch
        with self._lock:
            pending = self._pending
            if pending is None:
                _refuse()
            if (
                not isinstance(patch_id, str)
                or isinstance(conversation_epoch, bool)
                or not isinstance(conversation_epoch, int)
            ):
                _refuse()
            if patch_id != pending["artifact"]["patch_id"]:
                _refuse()
            if patch_id in self._approved_patch_ids:
                _refuse()
            if not self.plan_agent.is_reviewed_plan(pending["plan_id"]):
                _refuse()
            artifact_sha256 = pending["artifact_sha256"]
            if conversation_epoch != pending["conversation_epoch"]:
                _refuse()
            if conversation_epoch != self._conversation_epoch:
                _refuse()
            self._verify_artifact(pending)
            try:
                applier = self._applier(pending["workspace_root"])
                if applier.workspace.fingerprint != pending["workspace_fingerprint"]:
                    _refuse()
                admitted = applier.admit_target(pending["artifact"]["relative_paths"][0])
                with open(admitted.canonical_path, "rb") as handle:
                    source_bytes = handle.read()
                if _sha256(source_bytes) != pending["source_sha256"]:
                    _refuse()
            except (OSError, PatchAdmissionError):
                _refuse()
            approval_id = secrets.token_urlsafe(32)
            if approval_id == pending["artifact"]["patch_id"]:
                _refuse()
            self._approved_patch_ids.add(patch_id)
            self._approval = {
                "approval_id": approval_id,
                "patch_id": pending["artifact"]["patch_id"],
                "artifact_sha256": artifact_sha256,
                "plan_id": pending["plan_id"],
                "workspace_fingerprint": pending["workspace_fingerprint"],
                "relative_paths": list(pending["artifact"]["relative_paths"]),
                "source_hashes": list(pending["artifact"]["source_hashes"]),
                "output_hashes": list(pending["artifact"]["output_hashes"]),
                "diff_sha256": pending["diff_sha256"],
                "epoch": conversation_epoch,
                "conversation_epoch": conversation_epoch,
                "consumed": False,
            }
            return copy.deepcopy(self._approval)

    def decline(self, patch_id=None, epoch=None):
        """Invalidate the pending artifact and any unconsumed approval."""
        with self._lock:
            if self._pending is None:
                _refuse()
            if (
                patch_id is not None
                and patch_id != self._pending["artifact"]["patch_id"]
            ):
                _refuse()
            if epoch is not None and (
                isinstance(epoch, bool)
                or not isinstance(epoch, int)
                or epoch != self._pending["conversation_epoch"]
            ):
                _refuse()
            self._pending = None
            self._approval = None

    def invalidate(self):
        """Invalidate pending proposal/approval after a conversation reset."""
        with self._lock:
            self._pending = None
            self._approval = None
            self._conversation_epoch = None

    def _consume_approval(self, approval_id, conversation_epoch):
        with self._lock:
            approval = self._approval
            if approval is None:
                _refuse()
            if not isinstance(approval_id, str) or approval_id != approval["approval_id"]:
                _refuse()
            if approval["consumed"] or approval_id in self._consumed_approval_ids:
                _refuse()
            if conversation_epoch != approval["conversation_epoch"]:
                _refuse()
            if conversation_epoch != self._conversation_epoch:
                _refuse()
            pending = self._pending
            if pending is None:
                _refuse()
            if approval["artifact_sha256"] != pending["artifact_sha256"]:
                _refuse()
            if approval["diff_sha256"] != pending["diff_sha256"]:
                _refuse()
            if not self.plan_agent.is_reviewed_plan(approval["plan_id"]):
                _refuse()
            encoded, diff_bytes = self._verify_artifact(pending)
            if diff_bytes != pending["diff_bytes"]:
                _refuse()
            approval["consumed"] = True
            self._consumed_approval_ids.add(approval_id)
            return pending, encoded, approval

    def apply(self, approval_id, conversation_epoch=None, workspace_root=None, epoch=None):
        """Apply one approved artifact, consuming its approval exactly once."""
        if conversation_epoch is None:
            conversation_epoch = epoch
        try:
            with operation_journal_lock(self._journal_path()):
                return self._apply(
                    approval_id, conversation_epoch, workspace_root=workspace_root
                )
        except JournalLockError:
            self._clear_pending_state()
            _refuse()
        except PatchRefusal:
            # Any failed apply attempt invalidates the pending proposal and
            # approval.  This prevents a refused attempt from blocking the
            # user's next valid proposal.
            self._clear_pending_state()
            raise
        except Exception:
            # Unexpected provider/filesystem failures must also fail closed and
            # release the review state; no failed apply may remain retryable
            # against a partially trusted artifact.
            self._clear_pending_state()
            _refuse()

    def _apply(self, approval_id, conversation_epoch, workspace_root=None):
        with self._lock:
            if self._apply_in_progress:
                _refuse()
            self._apply_in_progress = True
            self._cancel_requested.clear()
        try:
            pending, encoded, approval = self._consume_approval(
                approval_id, conversation_epoch
            )
            if workspace_root is None:
                workspace_root = pending["workspace_root"]
            applier = self._applier(workspace_root)
            if applier.workspace.fingerprint != approval["workspace_fingerprint"]:
                _refuse()
            target = applier.admit_target(pending["artifact"]["relative_paths"][0])
            try:
                with open(target.canonical_path, "rb") as handle:
                    source_bytes = handle.read()
            except OSError:
                _refuse()
            if _sha256(source_bytes) != approval["source_hashes"][0]:
                _refuse()
            try:
                result = applier.apply_patch(
                    pending["patch"],
                    encoded,
                    expected_output_sha256=approval["output_hashes"][0],
                    expected_unified_diff=pending["diff_bytes"],
                    completion_callback=lambda entry, value, metadata=None: (
                        self._complete_mutation(applier, entry, value, metadata)
                    ),
                )
            except (PatchApplyError, PatchAdmissionError):
                with self._lock:
                    self._pending = None
                    self._approval = None
                _refuse()
            if result.state == "committed":
                if result.post_sha256 != approval["output_hashes"][0]:
                    _refuse()
                with self._lock:
                    self._pending = None
                    self._approval = None
                return {
                    "state": "committed",
                    "operation_id": result.operation_id,
                    "relative_path": result.relative_path,
                    "source_sha256": result.pre_sha256,
                    "output_sha256": result.post_sha256,
                    "pre_sha256": result.pre_sha256,
                    "post_sha256": result.post_sha256,
                    "backup_reference": result.backup_reference,
                }
            with self._lock:
                self._pending = None
                self._approval = None
            return {
                "state": "uncertain",
                "operation_id": result.operation_id,
                "relative_path": result.relative_path,
                "source_sha256": result.pre_sha256,
                "output_sha256": result.post_sha256,
                "pre_sha256": result.pre_sha256,
                "post_sha256": result.post_sha256,
                "backup_reference": result.backup_reference,
                "guidance": (
                    "Approved bytes may have been applied. Verify the current file "
                    "hash against pre_sha256 and post_sha256. The backup path is "
                    "the only supported recovery evidence."
                ),
            }
        finally:
            with self._lock:
                self._apply_in_progress = False

    def _complete_mutation(self, applier, entry, result, metadata=None):
        """Completion seam used by tests and normal journal persistence."""
        applier.complete_mutation(entry, result, metadata)

    def undo_last(self, workspace_root, epoch):
        """Undo the latest committed operation with C3-I2 hash safeguards."""
        with self._lock:
            if (
                isinstance(epoch, bool)
                or not isinstance(epoch, int)
                or epoch != self._conversation_epoch
            ):
                _refuse()
        try:
            with operation_journal_lock(self._journal_path()):
                try:
                    applier = self._applier(workspace_root)
                    applier.undo_last()
                except (PatchRecoveryError, PatchApplyError, PatchAdmissionError):
                    _refuse()
        except JournalLockError:
            _refuse()

    def redo_last(self, workspace_root, epoch):
        """Redo the latest undone operation with C3-I2 hash safeguards."""
        with self._lock:
            if (
                isinstance(epoch, bool)
                or not isinstance(epoch, int)
                or epoch != self._conversation_epoch
            ):
                _refuse()
        try:
            with operation_journal_lock(self._journal_path()):
                try:
                    applier = self._applier(workspace_root)
                    applier.redo_last()
                except (PatchRecoveryError, PatchApplyError, PatchAdmissionError):
                    _refuse()
        except JournalLockError:
            _refuse()

    def _journal_path(self):
        if self.operation_log_path:
            return self.operation_log_path
        return PatchApplier.DEFAULT_OPERATION_LOG_PATH

    def _clear_pending_state(self):
        """Drop the current proposal and any approval after a failed apply."""
        with self._lock:
            self._pending = None
            self._approval = None

    # Stable public names used by the GUI and acceptance contract.
    propose_patch = propose
    approve_patch = approve
    decline_patch = decline
    invalidate_pending_patch = invalidate
    apply_patch = apply

    def cancel_patch(self, patch_id, epoch):
        """Cancel one pending proposal before any mutation begins."""
        with self._lock:
            pending = self._pending
            if pending is None or pending["artifact"]["patch_id"] != patch_id:
                _refuse()
            if (
                isinstance(epoch, bool)
                or not isinstance(epoch, int)
                or pending["conversation_epoch"] != epoch
            ):
                _refuse()
            self._pending = None
            self._approval = None
