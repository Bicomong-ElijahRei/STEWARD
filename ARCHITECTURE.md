# STEWARD v2 — Architecture Map

Read this FIRST. It exists so no session ever re-discovers the system by reading 15 files.

## System in one paragraph
Desktop AI file organizer. CustomTkinter GUI (`main.py` -> `gui/main_window.py`) drives a
Supervisor (`agents/supervisor.py`) that classifies intent, a Router (`core/router.py`) that
picks a provider, and a FileAgent (`agents/file_agent.py`) that previews, gets approval for,
and executes sandboxed file operations with undo/redo. SQLite + Fernet (`core/database.py`)
stores providers/usage/traces. A watchdog daemon (`agent/daemon.py`) watches a folder.

## Module roles
- `core/router.py`      APIManager: provider selection, cooldown, 429/401/5xx handling, `_steward` metadata
- `core/database.py`    DatabaseManager: Fernet-encrypted providers, usage_ledger, traces; singleton via init_db/get_db
- `core/discovery.py`   OpenRouter free-model discovery (Phase 4/5)
- `core/validator.py`   latency/intelligence/tool probes
- `agents/supervisor.py` Cortex: intent -> strict JSON {agent, action}
- `agents/file_agent.py` Foldy: tool schema, sandbox, plan approval, undo/redo, operation log
- `agent/tools.py`       LEGACY module-level filesystem helpers; `tool_functions` dict is the dispatch target
- `agent/daemon.py`      watchdog handler; calls FileAgent.categorise_file
- `gui/main_window.py`   StewardGUI: builds ONE shared APIManager/Supervisor/FileAgent, passes FileAgent to BOTH Chat and Organizer
- `gui/chat_tab.py`      chat + approval flow + Live Feed wiring
- `gui/organizer_tab.py` preview table, execute, undo slider, daemon start/stop
- `gui/settings_tab.py`  API Hub: provider CRUD, validation, discovery, assigned_agent dropdown
- `gui/live_feed.py`     activity cards + provider failover flash

## The two critical paths
Chat request: send_chat -> supervisor.route -> AGENT_ROUTING_KEYS -> FileAgent.run(dry_run=True)
File op approval: run() stores deep-copied parsed plan + uuid4 plan id under _plan_lock
  -> ChatTab captures id AT PREVIEW TIME -> user approves -> execute_pending_plan(plan_id)
  -> _execute_tool_plan(dry_run=False) -> allowlist + path preflight -> _legacy_tool_functions[name]

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

## Known-open issues (ledger)
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
  Sorted media incl. large .mkv, L5 init_db key_path + close() singleton.

## Environment gotchas (cost a whole session once — do not repeat)
- PowerShell 5.1: `&&` invalid; `rg` and `tail` do not exist; pytest NOT installed (use unittest)
- gui/chat_tab.py and gui/main_window.py START WITH A UTF-8 BOM. Read with utf-8-sig or bytes.
  A default-encoding read yields a FAKE SyntaxError U+00BB. Never "fix" the file for it.
- Protected: steward.db, secret.key, steward_operations.json. Tests use tempfile +
  patch.object(FileAgent,"OPERATION_LOG_PATH",...) AND pin the instance attribute.
- Helper scripts go OUTSIDE the repo. Preserve BOM and line endings byte-for-byte.
- test_validator.py is standalone: `python test_validator.py`

## Tests
- test_phase0_phase_a.py — 34 tests. Run: `python -m unittest discover -v`
- Security tests MUST enter via execute_pending_plan() with a hostile plan, not convenience methods
- Proof standard: RED -> fix -> GREEN. Safety items also get mutation proof
  (patch the guard out, show RED, restore, show GREEN)

## Gates (each as its own command)
python -m unittest discover -v
python test_validator.py
python -m compileall -q . -x '[\\/]venv[\\/]'
git diff --check && git diff --stat && git status --short
Get-FileHash steward.db,secret.key