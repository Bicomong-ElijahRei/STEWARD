# STEWARD — Architecture Map

Read this FIRST. It exists so no session ever re-discovers the system by reading 15 files.

## System in one paragraph
Desktop AI file organizer. CustomTkinter GUI (`main.py` -> `gui/main_window.py`) drives a
Supervisor (`agents/supervisor.py`) that classifies intent, a Router (`core/router.py`) that
picks a provider, a FileAgent (`agents/file_agent.py`) that previews, gets approval for, and
executes sandboxed file operations with undo/redo, and a text-only CodingAgent
(`agents/coding_agent.py`) for provider-backed coding suggestions. SQLite + Fernet
(`core/database.py`) stores providers/usage/traces in `%APPDATA%\STEWARD`. A watchdog daemon
(`agent/daemon.py`) watches a folder, and a restart-safe scheduled scanner handles recurring
file categorization.

## Module roles
- `core/router.py`      APIManager: provider selection, cooldown, 429/401/5xx handling, `_steward` metadata
- `core/database.py`    DatabaseManager: Fernet-encrypted providers, usage_ledger, traces; singleton via init_db/get_db; shared credentials support explicit ID rotation with endpoint/provider-link validation and rollback
- `core/discovery.py`   OpenRouter free-model discovery (Phase 4/5)
- `core/validator.py`   latency/intelligence/tool probes
- `agents/supervisor.py` Cortex: intent -> strict JSON {agent, action}
- `agents/file_agent.py` Foldy: tool schema, sandbox, plan approval, undo/redo, operation log
- `agent/journal_lock.py` persistent sidecar + OS-managed cross-process operation-journal lock
- `agents/rag_agent.py`     Scout: persistent ChromaDB ingestion, chunking, embeddings, retrieval, source replacement
- `agents/coding_agent.py`  Syntax: provider-backed generation/debug/refactoring/review/explanation; text-only, no tools/files/processes
- `agent/tools.py`       LEGACY module-level filesystem helpers; `tool_functions` dict is the dispatch target
- `agent/daemon.py`      watchdog handler and ScheduledScanner; identity-aware dedup, bounded workers, generation-safe cancellation
- `gui/main_window.py`   StewardGUI: builds ONE shared APIManager/Supervisor/FileAgent/CodingAgent, passes FileAgent to BOTH Chat and Organizer
- `gui/chat_tab.py`      chat + approval flow + Live Feed wiring + bounded Cortex conversation + epoch-guarded UI
- `gui/organizer_tab.py` preview table, execute, undo slider, daemon start/stop, scheduled-scan controls
- `gui/settings_tab.py`  API Hub: provider CRUD, validation, discovery, assigned_agent dropdown, explicit credential rotation
- `gui/live_feed.py`     activity cards + provider failover flash

## The critical paths
Chat request: send_chat -> supervisor.route -> AGENT_ROUTING_KEYS -> specialist agent
File op approval: run() captures a preview generation and stores a deep-copied parsed plan
  + uuid4 plan id under _plan_lock -> ChatTab receives the request-local id through
  plan_id_callback -> user approves -> execute_pending_plan(plan_id)
  -> _execute_tool_plan(dry_run=False) -> allowlist + path preflight -> _legacy_tool_functions[name]
Discarding, superseding, or clearing chat advances the preview generation, so a late provider
response cannot publish an executable plan or overwrite newer provider metadata.
Scout retrieval: supervisor.route -> AGENT_RAG -> ChatTab._get_rag_agent (lazy ./rag_index)
  -> RAGAgent.search -> ChromaDB query -> source/content/distance results -> formatted Chat bubble
General conversation: supervisor.route -> AGENT_GENERAL_CHAT -> bounded in-memory history
  -> APIManager.route_request(agent_name="Cortex", require_tools=False) -> epoch check -> chat bubble
Syntax coding: supervisor.route -> AGENT_CODING -> CodingAgent.handle_request
  -> APIManager.route_request(agent_name="Syntax", require_tools=False, no tools) -> text-only result
  -> one of five intent instructions: generation, debugging, refactoring, review, explanation

## Sandbox rules (do not weaken)
- Roots: <root_path>/Incoming and <root_path>/Sorted only; root_path defaults to os.getcwd()
- _sandbox_path: realpath + abspath + commonpath + normcase; cross-drive ValueError is expected
- BOTH reads and writes are validated: read_file_content/get_file_info (file_path),
  list_directory/find_duplicates/find_large_files/suggest_deletions (directory)
- Dispatch allowlist is DERIVED from _get_tool_definitions() inside _execute_tool_plan.
  Undeclared tools (cleanup_temp_files, batch_move, ...) must stay unreachable.
- Preflight runs only when dry_run=False; it rejects the WHOLE plan before the first mutation.

## Router semantics
- Sort by speed_score_ms; cloud first, at most one local
- 429 -> cooldown_until from Retry-After, record_usage, prefer another key on SAME endpoint
- 401/403 -> is_active=0. 5xx -> failure_count++, >3 -> 5 min cooldown
- Success resets failure_count/cooldown; injects `_steward` {provider, model, agent_name, failovers}
- Tool-bearing requests only use providers with `supports_tools=True`; there is no fallback to
  a text-only provider.
- Provider HTTP calls have a 30-second default timeout, so an in-flight daemon request cannot
  hold process exit indefinitely.

## Conversation and Syntax boundaries
- Cortex general-chat memory is instance-local and bounded to 6 turns, 12,000 total characters,
  and 4,000 characters per message. Clearing chat erases history and increments an epoch.
- Requests capture that epoch before routing/provider work; stale responses and queued UI
  callbacks are discarded across general chat, file preview/approval/execution, Scout, Syntax,
  provider reporting, Live Feed, and delegation. History snapshots and turn writes are protected
  by one instance lock. Clear invalidates pending/in-flight file previews in the same critical
  section; the final execution check and plan claim are serialized with that invalidation.
- Provider metadata is delivered through request-local callbacks for Cortex, Foldy, and
  Syntax. Shared ``last_provider`` remains available for compatibility but cannot misattribute
  one concurrent request's provider to another request.
- Delegated Syntax original-request context is thread-local, so overlapping requests cannot
  replace one another's intent context.
- Syntax is deliberately text-only. It sends `agent_name="Syntax"` with `require_tools=False`
  and no tool definitions, and has no filesystem or process-execution API. Empty, malformed,
  and tool-bearing provider responses are rejected.

## Daemon lifecycle
- `last_processed` keeps path keys for inspection compatibility but stores filesystem identity;
  a deleted/recreated path is eligible for processing again.
- Four daemon worker threads consume a bounded queue; at most 32 files are outstanding
  (queued or active). Queue admission uses timed, stop-responsive backpressure.
- `stop()` prevents new work, discards queued files, and joins workers briefly. Workers are
  daemon threads, so an active provider call cannot delay interpreter exit.
- `ScheduledScanner` uses a generation-specific cancel event and tracks active scans. Cancellation
  is checked between file operations; a timed-out stop returns `False`. Restarting creates a new
  isolated generation even if an old worker is still unwinding; the scan mutex prevents
  overlapping scan bodies, and the old generation cannot commit shared state or notifications.

## Historical issue ledger (all entries below closed)
Batch 2A: H5 router skips a candidate + double-hits the promoted one (total failure possible
  with a healthy provider present); M4 InvalidToken bricks app; M5 re-verify resets
  assigned_agent; L1 Click unbindable + tier exact-match; N1 ChatTab finally lacks lifecycle
  guard; N2 input lock is UI-only; N4 error contract inconsistent; N5 private attr access.
Batch 2B: H6 undo marks delete/non-empty/unknown as undone + redo is FIFO; M6 log non-atomic,
  non-unique ids, no collision check, no list validation; M1 undo/redo declared but
  undispatchable (and _lock is NOT reentrant — deadlock risk if wired naively); N3 preview
  doesn't warn about doomed plans.
Batch 3: M2 daemon never moves (dry_run), M3 shared dry_run flag, M7 whole-file hash,
  M8 organizer builds widgets on worker thread, N6 daemon dest_base vs hardcoded roots,
  L2 unguarded scroll + unbounded waits, L3 shutdown cross-thread, L4 tracked pycache/.vscode/
  Sorted media incl. large .mkv, L5 init_db key_path + close() singleton. The later Snoop & Fix
  passes closed the daemon concurrency/lifecycle gaps and bounded GUI approval waits.

## Environment gotchas (cost a whole session once — do not repeat)
- PowerShell 5.1: `&&` invalid; `rg` and `tail` do not exist; pytest NOT installed (use unittest)
- gui/chat_tab.py and gui/main_window.py START WITH A UTF-8 BOM. Read with utf-8-sig or bytes.
  A default-encoding read yields a FAKE SyntaxError U+00BB. Never "fix" the file for it.
- Persistent state: `%APPDATA%\STEWARD\steward.db`, `secret.key`, and `steward_operations.json`;
  legacy repository-root files are copied, never moved or overwritten. Tests use tempfile +
  patch.object(FileAgent,"OPERATION_LOG_PATH",...) AND pin the instance attribute.
- Mutation publication is no-overwrite: a same-directory temporary copy is reserved at the
  destination with a hard link when supported, otherwise an `O_EXCL` file descriptor. The
  source is removed only after destination publication succeeds. Rename and undo/redo use the
  same primitive rather than `os.rename`/`shutil.move` overwrite behavior.
- Operation-history writes use a unique same-directory temporary file, flush, `fsync`, and
  atomic replacement; non-Windows hosts also fsync the containing directory. A persistent
  `<operation-log>.lock` sidecar provides an OS-managed exclusive lock (`msvcrt.locking` on
  Windows, `fcntl.flock` on POSIX), while a keyed in-process `RLock` preserves thread safety.
  The default acquisition timeout is 10 seconds; timeout or lock API failure fails closed before
  mutation. The sidecar is never deleted, and the OS releases its lock on normal exit or process
  termination. The cross-process lock covers the complete read/merge/revision-check/atomic-replace
  section and the complete write-ahead mutation / undo-redo claim, filesystem action, and completion
  lifecycle. Windows behavior is locally tested; the POSIX implementation is documented but not
  locally tested on this Windows host.
- Mutation intent is persisted before disk mutation and completion afterward. Interrupted
  intents/transitions reload as `uncertain` and block blind undo/redo. A published move/rename
  whose source removal fails records `failed` only after destination rollback is verified; if
  cleanup cannot be verified, it records `uncertain`. Folder operations record exact
  created-directory identities; partial creation preserves that evidence and is uncertain.
  Legacy records without this evidence are refused for destructive undo/redo.
- Whole-plan preflight includes file and directory targets. A file/directory target collision is
  rejected in either plan order before the first mutation, while a directory parent with a file
  child remains valid.
- Helper scripts go OUTSIDE the repo. Preserve BOM and line endings byte-for-byte.
- test_validator.py is standalone: `python test_validator.py`

## Tests
- test_phase0_phase_a.py — main regression suite. Run: `python -m unittest discover -v`
- test_lifecycle_hardening.py — generation/epoch ownership regressions
- test_appdata_migration.py — copy-only migration tests
- test_filesystem_journal_hardening.py — collision, ownership, write-ahead, partial-outcome, no-op, and journal-failure regressions
- test_filesystem_journal_cross_process.py — real-process concurrent journal, undo/redo claim, timeout, and crash-release regressions
- Total discovery count is 266
- Security tests MUST enter via execute_pending_plan() with a hostile plan, not convenience methods
- Proof standard: RED -> fix -> GREEN. Safety items also get mutation proof
  (patch the guard out, show RED, restore, show GREEN)

## Shared-credential migration
- Preferred CLI: `tools/migrate_live.py`; dry-run is the default and operates only on a
  temporary SQLite copy.
- Live execute/rollback requires explicit confirmation (300-second timeout), then creates and
  verifies a persistent database/key/operation-log backup set with a SHA-256 manifest.
- Post-flight validation checks integrity, provider count, and decryptability of every linked
  provider; validation failure triggers logical rollback. `tools/run_migration.py` is only a
  compatibility wrapper around this guarded workflow.

## Gates (each as its own command)
python -m unittest discover -v
python test_validator.py
python -m compileall -q . -x '[\\/]venv[\\/]'
git diff --check && git diff --stat && git status --short
Get-FileHash "$env:APPDATA\STEWARD\steward.db","$env:APPDATA\STEWARD\secret.key"
