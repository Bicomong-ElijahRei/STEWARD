# STEWARD — Architecture Map

Read this FIRST. It exists so no session ever re-discovers the system by reading 15 files.

## System in one paragraph
Desktop AI file organizer. CustomTkinter GUI (`main.py` -> `gui/main_window.py`) drives a
Supervisor (`agents/supervisor.py`) that classifies intent, a Router (`core/router.py`) that
picks a provider, a FileAgent (`agents/file_agent.py`) that previews, gets approval for, and
executes sandboxed file operations with undo/redo, a text-only CodingAgent
(`agents/coding_agent.py`) for provider-backed coding suggestions, and a PlanAgent
(`agents/plan_agent.py`) for approval-gated, text-only meta-prompting. Code context is
provided by a bounded read-only CodeIndexAgent (`agents/code_index_agent.py`). SQLite + Fernet
(`core/database.py`) stores providers/usage/traces in `%APPDATA%\STEWARD`. A watchdog daemon
(`agent/daemon.py`) watches a folder, and a restart-safe scheduled scanner handles recurring
file categorization.

## Module roles
- `core/router.py`      APIManager: provider selection, cooldown, 429/401/5xx handling, `_steward` metadata
- `core/database.py`    DatabaseManager: Fernet-encrypted providers, usage_ledger, traces; singleton via init_db/get_db; shared credentials support explicit ID rotation with endpoint/provider-link validation and rollback
- `core/discovery.py`   OpenRouter free-model discovery (Phase 4/5)
- `core/validator.py`   latency/intelligence/tool probes
- `agents/supervisor.py` Cortex: intent -> strict JSON {agent, action}; supported categories route to specialists, OUT_OF_SCOPE is a truthful non-actionable refusal, and generic invalid categories remain UNKNOWN
- `agents/file_agent.py` Foldy: tool schema, sandbox, plan approval, undo/redo, operation log
- `agent/journal_lock.py` persistent sidecar + OS-managed cross-process operation-journal lock
- `agents/rag_agent.py`     Scout: persistent ChromaDB ingestion, chunking, embeddings, retrieval, source replacement
- `agents/code_index_agent.py` Code context: separate `steward_code` collection; explicit-root bounded read-only indexing, AST/fallback chunks, static import/call graph derivation and traversal, incremental replacement, scoped semantic/dependency retrieval
- `agents/chroma_lifecycle.py` shared persistent-client close/finalization boundary used by RAG and code-index agents
- `agents/coding_agent.py`  Syntax: provider-backed generation/debug/refactoring/review/explanation; text-only, no tools/files/processes
- `agents/plan_agent.py`   PlanAgent: strict Cortex blueprint validation, immutable app-owned plan artifacts, single-use ID-bound review gate, separate text-only Syntax elaboration (C2: `1c66ecb9`)
- `agents/patch_engine.py` C3-I1 pure patch staging: strict one-file artifact/schema validation, definition AST anchors, byte-preserving replace/insert splicing, deterministic diff, and outside-edit byte proof; no I/O, mutation, approval, persistence, or execution
- `agents/patch_applier.py` C3-I2 admitted content replacement: one-file workspace/target admission, proof/source revalidation, durable journal transitions, exact backups, and hash-guarded undo/redo
- `agents/patch_review.py` C3-I3 review facade: provider proposal, immutable exact-diff artifact, epoch/workspace/hash-bound single-use approval, guarded apply, and fail-closed lifecycle invalidation
- `agents/healing_controller.py` C4-I1 pure iteration controller: bounded self-healing loop over INJECTED executor/journal/cancellation/proposal interfaces; structural hard iteration bound, write-ahead intent/outcome/terminal journal ordering, deterministic bounded+redacted observations, and truthful termination states. It performs NO execution (no process, shell, or dynamic-code surface), cannot apply patches, and reaches C3 only through a proposal request
- `agents/mcp_resource_core.py` D1-I1 pure MCP resource admission core: standard-library-only, transport-agnostic admission/read boundary for one explicitly selected identity-pinned remote resource server; HTTPS/effective-origin pinning, explicit resource allowlisting, SHA-256 snapshot re-verification, byte bounds, deterministic redaction/truncation, typed refusals, single-admission revocation, and immutable external-only result containers. It imports no MCP SDK and performs no network, filesystem, subprocess, dynamic-code, JSON-RPC, GUI, tool, or local mutation operation
- `gui/patch_review_dialog.py` C3-I3 workspace/target picker, exact-diff preview, explicit approval/apply, truthful recovery states, and one bounded daemon-worker slot with epoch/closed-guarded UI marshaling
- `agent/content_replace.py` C3-I2 atomic overwrite primitive: same-directory verified staging plus `os.replace`, with regular-file, same-directory, and pre/post hash guards
- `agent/tools.py`       LEGACY module-level filesystem helpers; `tool_functions` dict is the dispatch target
- `agent/daemon.py`      watchdog handler and ScheduledScanner; identity-aware dedup, bounded workers, generation-safe cancellation
- `gui/main_window.py`   StewardGUI: builds ONE shared APIManager/Supervisor/FileAgent/CodingAgent/PlanAgent/PatchReviewManager; passes FileAgent to BOTH Chat and Organizer
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
Syntax coding: supervisor.route -> AGENT_CODING -> CodeIndexAgent.search (only when an
  explicit root has been indexed) -> bounded root-scoped semantic/dependency expansion ->
  CodingAgent.handle_request with <=5 path/line snippets
  -> APIManager.route_request(agent_name="Syntax", require_tools=False, no tools) -> text-only result
  -> one of five intent instructions: generation, debugging, refactoring, review, explanation
Meta-prompting: Chat **Plan first** -> validated supervisor CODING category
  -> PlanAgent.architect -> Cortex strict JSON blueprint -> app-assigned UUID
  -> immutable artifact under `%APPDATA%\STEWARD\plans` -> explicit plan-ID approval
  -> PlanAgent.build_plan -> separate Syntax text-only request -> suggestion bubble
  Targets remain informational; no FileAgent call or file change occurs in C2.
Patch staging (not user-integrated): already-admitted source bytes + strict raw artifact
  -> `decode_patch_artifact` -> `stage_patch` -> staged bytes + deterministic diff + proof.
  This path performs no workspace/path resolution, file access, mutation, approval, artifact
  persistence, target import, execution, lint, or test.
C3-I2 admitted replacement: explicit workspace + one `.py`
  target -> path/reparse/root/size admission -> C3-I1 staging -> re-derived proof and source
  identity/hash checks -> durable journal intent -> exact app-owned pre/post backup ->
  same-directory hash-checked staging -> `os.replace` -> durable completion. Undo/redo is
  journal-locked and hash-guarded. This path never executes, imports, lints, or tests the target.
C3-I3 user-integrated review: Chat **Patch Review** -> latest reviewed plan ID + explicit
  workspace/target -> Tk-thread input snapshot -> one bounded daemon worker -> existing manager
  proposal -> C3-I1/C3-I2 staging -> immutable write-once exact-diff artifact ->
  epoch/workspace/source/output/artifact-bound single-use approval -> journal-locked C3-I2 apply.
  Worker results return through ChatTab's epoch-aware scheduler. One apply runs at a time;
  captured-input controls are disabled during work and restored on completion/refusal/failure.
  Closing the dialog or clearing chat invalidates the proposal/approval and closes the dialog;
  stale, closed, or superseded worker results cannot publish a preview, approval, result, control
  state, or Live Feed event.
Code indexing: Chat **Code Index** control -> explicit folder -> daemon worker
  -> CodeIndexAgent.index_project -> separate persistent `steward_code` Chroma collection
  -> queue -> main-thread status/Live Feed update; cancellation and job/conversation epochs
  reject stale worker results
C4-I1 pure healing controller (not user-integrated): injected executor + injected
  journal -> structural pre-iteration bound check -> durable `intent` record ->
  injected executor call -> durable `outcome` record (bounded, redacted observation)
  -> terminal `terminal` record. Termination is deterministic on bound reached,
  success, unrecoverable error, executor exception, invalid result, cancellation,
  repeated identical failure, iteration/total timeout, and journal failure. The
  controller starts no process, applies no patch, and may only request that a
  proposal enter the existing C3 single-use exact-diff approval gate. No executor,
  sandbox, GUI wiring, or provider call exists; C4 remains BACKLOG.
C4-ISO isolation decision (research only): `docs/windows_isolation_research.md`
  evaluates all 20 C4-I2 criteria and defers execution because no supported
  baseline is proven on this Windows Home host.
D1-I1 pure MCP resource admission (not user-integrated): explicit server identity +
  exact expected server identity -> canonical HTTPS identity/effective origin -> explicit
  canonical resource allowlist -> injected transport server snapshot -> tools-capability,
  advertised-resource, duplicate/count/type, and fingerprint checks -> single immutable
  admission -> fingerprint re-verification immediately before an injected read -> per-resource/
  total byte bounds -> deterministic redaction/truncation -> immutable external-only container.
  Only the admitted server's canonical origin may supply resources. Any server advertising
  a tools capability is refused wholesale. Revocation or successful re-admission invalidates
  the prior admission and cached content. The result container is permanently ineligible for
  supervisor routing and native-tool use. No transport, SDK dependency, chat surface, or
  runtime MCP capability exists in D1-I1.

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
- Supervisor categories map only to supported routing targets. OUT_OF_SCOPE is a non-actionable
  refusal, while malformed or arbitrary categories remain UNKNOWN; retired category emissions
  are normalized to OUT_OF_SCOPE without retaining the exact legacy token in active source.

## Conversation and Syntax boundaries
- Cortex general-chat memory is instance-local and bounded to 6 turns, 12,000 total characters,
  and 4,000 characters per message. Clearing chat erases history and increments an epoch.
- Requests capture that epoch before routing/provider work; stale responses and queued UI
  callbacks are discarded across general chat, file preview/approval/execution, Scout, Syntax,
  Patch Review proposal/apply, provider reporting, Live Feed, and delegation. Patch Review
  workers call only the existing manager and publish no preview, approval, result, control state,
  or feed event after close, clear, or epoch change. History snapshots and turn writes are protected
  by one instance lock. Clear invalidates pending/in-flight file previews in the same critical
  section; the final execution check and plan claim are serialized with that invalidation.
- Provider metadata is delivered through request-local callbacks for Cortex, Foldy, and
  Syntax. Shared ``last_provider`` remains available for compatibility but cannot misattribute
  one concurrent request's provider to another request.
- Delegated Syntax original-request context is thread-local, so overlapping requests cannot
  replace one another's intent context.
- Plan artifacts are app-assigned UUID JSON files under `%APPDATA%\STEWARD\plans`,
  written once through a same-directory temporary file, flush, fsync, and atomic replace.
  Blueprint keys, types, lengths, list counts, and total size are bounded before persistence.
  A plan ID is approved once; unknown, stale, superseded, replayed, and cleared IDs share
  one refusal contract. Plan targets are informational and never passed to FileAgent.
- Syntax is deliberately text-only. It sends `agent_name="Syntax"` with `require_tools=False`
  and no tool definitions, and has no filesystem or process-execution API. Empty, malformed,
  and tool-bearing provider responses are rejected.
- Code context changes only the user message: at most five snippets, 2,000 characters per
  snippet, and 8,000 total characters including headers are formatted with relative path,
  line range, and symbol. With no index, the existing Syntax prompt is unchanged. Indexing
  never imports, executes, or modifies source.

## AST patch staging and admitted replacement rules
- C3-I1 is a pure internal staging foundation. It accepts one already-admitted source file
  and performs no path resolution, filesystem access, mutation, approval, persistence,
  journal, undo, target import, execution, lint, or test.
- The raw artifact is strict UTF-8 JSON with duplicate keys rejected. Top-level, file, edit,
  and anchor key sets are exact; the decoded artifact and supplied object must agree.
- V1 admits one file and at most 20 edits using only `replace_node`, `insert_before`, and
  `insert_after` over function/class definitions. `delete_node` is unsupported.
- Bounds are 16 KiB per edit (replacement plus anchor metadata), 256 KiB per raw artifact,
  and 1 MiB for each input and output file.
- Only UTF-8 is accepted. A UTF-8 BOM and the declared LF/CRLF mode are preserved; invalid
  UTF-8, UTF-16, mixed newline modes, and final-newline changes are refused.
- Original and output are parsed with `ast` only. Proof is exact byte equality outside the
  declared edited ranges, not AST equivalence. The output diff and proof are deterministic.
- C3-I2 adds a separate mutation/recovery surface for exactly one explicitly selected existing
  `.py` file. C3-I3 exposes it through the Patch Review dialog behind an immutable exact-diff,
  single-use approval artifact.
- Workspace admission rejects drive/home/app-data roots, overlap with Incoming or Sorted,
  and backup-root overlap with all three. Target admission rejects traversal/absolute paths,
  non-Python and denied names, symlink/junction/reparse components, non-regular files, and
  sources over 1 MiB. The workspace fingerprint binds canonical path plus filesystem identity.
- C3-I2 re-derives the C3-I1 output and outside-range byte proofs, verifies the output hash,
  and revalidates target path, filesystem identity, and source hash before replacement.
- The replacement primitive stages unique verified bytes in the target's own directory,
  requires regular non-link target/staged files, verifies both pre- and post-image hashes,
  and uses `os.replace`. It never creates a missing target directory.
- Journal intent is durable before backup and replacement; completion is durable afterward.
  Intent-write failure performs zero target writes. A post-boundary failure is classified by
  observed target hash as committed, failed, or uncertain. Exact pre/post bytes are backed
  up outside the workspace with a metadata-only manifest; partial backups are removed.
- Undo and redo are journal-locked, hash-guarded, and blocked by uncertain content edits.
  A proven pre-mutation refusal is retryable; a failure after the replacement boundary is
  uncertain. Redo preserves the existing FIFO order.
- C3-I2 never executes, imports, lints, or tests target code.
- C3-I3 writes the review artifact once under `%APPDATA%\STEWARD\patches`. A separate approval
  ID binds the conversation epoch, reviewed plan ID, canonical workspace fingerprint, relative
  target, source/output hashes, exact-diff SHA-256, and artifact SHA-256. Changed source/workspace/
  artifact/diff/plan/epoch, stale/replayed approval, journal-lock contention, or failed apply
  refuses and clears pending review state. A new proposal may replace only an unapproved preview;
  it cannot strand an approved artifact. Content recovery is scoped to the selected workspace
  fingerprint so one workspace cannot undo another workspace's operation.

## ChromaDB lifecycle rules
- RAGAgent and CodeIndexAgent own their persistent ChromaDB clients. Reinitialization closes the
  existing client before creating its successor, and initialization rollback closes a newly created
  client after collection setup fails.
- Close failures are not suppressed: the agent clears its collection reference, retains the client
  reference for diagnosis or retry, and raises a contextual `RuntimeError`.
- ChromaDB 1.5.9's `Client.close()` stops the shared Chroma system, but its Rust-owned SQLite pool
  can remain alive until Python finalizes the binding reference cycle. The shared lifecycle helper
  therefore runs a standard-library collection pass after successful close. This releases
  `chroma.sqlite3` on Windows without accessing Chroma internals or suppressing close errors.

## Code-index safety rules
- `steward_code` is separate from Scout's `steward_docs`; clearing code context does not clear
  document RAG and clearing document RAG does not clear code context.
- A root is explicit. Traversal uses realpath/abspath/commonpath/normcase and refuses
  symlink/junction targets outside the selected root. The selected root's own basename is
  also denied when it is `.git`, a cache directory, `venv`, `node_modules`, `rag_index`, or
  `media`. `.env*`, `*.key`, `*.db`, `secret.key`, and `steward_operations.json` remain
  denied by filename rules.
- Default bounds are 2,000 files, 256 KiB per file, 2,400-character chunks, and 240-character
  overlap. The report states truncation and file-limit conditions deterministically.
- Python is chunked by top-level AST function/class boundaries with overlapping-window
  fallback. Non-Python and invalid Python use bounded overlapping windows.
- During the same admitted read, Python AST analysis derives bounded identifier-only import
  and call facts. Resolution uses name-based lookup against the admitted root inventory only;
  it never imports or executes source and never reads external, unresolved, denied, or
  out-of-root module strings. Dynamic imports, aliases, ambiguous symbols, and runtime
  dependency behavior remain unresolved approximations.
- Import/call edges are stored as bounded scalar JSON metadata on the first chunk of each
  file. Traversal is root-scoped and bounded by depth, visited nodes, edges per node, imports
  and calls per file, total edges, and metadata characters. Changed/deleted files reconcile
  their edges during the existing incremental rebuild.
- Chunk IDs and metadata are root-scoped. A content hash replaces changed chunks and removes
  chunks for deleted files; the most recently indexed root is persisted in collection
  metadata so retrieval does not mix projects.
- The local collection stores plaintext excerpts. Retrieved excerpts are sent to the
  configured Syntax provider (cloud-first unless explicitly configured otherwise); the GUI
  discloses this before indexing.

## MCP resource admission and isolation rules
- D1-I1 (`agents/mcp_resource_core.py`) is a pure core, not a transport. The only external
  boundary is an injected protocol exposing `describe_server(identity)` and
  `read_resource(identity, resource_uri)`. D1-I1 does not import or select an MCP SDK version.
- Identities and resource URIs must be canonical HTTPS URLs. Userinfo, fragments, malformed
  percent escapes, and every query-bearing URL are refused. Literal loopback, private, reserved,
  link-local, multicast, and unspecified addresses plus localhost/local-domain suffixes fail
  closed. Public IDNA and IPv6 hosts canonicalize deterministically.
- The effective origin includes the explicit/default port. Identity and every allowed resource
  are pinned to that origin; canonical-equivalent duplicates fail closed.
- The server-reported identity must exactly equal the caller's expected identity. A server
  advertising any tools capability is refused wholesale, even if it also advertises resources.
  This v1 compatibility cost is intentional: D1-I1 never invokes tools and does not partially
  admit a tools-capable server.
- The resource allowlist is explicit and unique. Every listed canonical URI must be advertised
  by the server. The SHA-256 fingerprint covers normalized identity, reported server identity,
  normalized capabilities, and order-independent canonical advertised resources, and is
  re-verified before every read.
- Per-resource, per-admission-total, resource-count, and URI-length bounds fail closed.
  Deterministic assignment-name-preserving redaction and private-key redaction run before
  deterministic UTF-8 truncation. Transport exceptions become the bounded
  `transport_failure` refusal.
- Exactly one server is admitted at a time. Successful re-admission and explicit revocation
  invalidate the prior admission and cached content. Failed admission does not clear a valid
  prior admission.
- Results are core-constructed immutable `UntrustedExternalResource` values with permanent
  `routing_eligible=False` and `native_tool_eligible=False`. They cannot enter supervisor routing
  or native-tool context merely by being passed to a caller.

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
- test_code_context.py — code-index traversal/bounds/retrieval, Syntax context, and GUI invalidation regressions
- test_patch_engine.py — pure C3-I1 artifact, anchor, splicing, encoding, proof, determinism, and purity regressions
- test_patch_applier.py — C3-I2 workspace/target admission, proof/source revalidation, atomic replacement, journal/backup states, and guarded undo/redo regressions
- test_patch_review.py — C3-I3 exact-diff artifact/approval, lifecycle invalidation, hostile input, workspace isolation, truthful recovery, GUI, and real-process contention regressions
- test_patch_review_workers.py — Patch Review off-main execution, epoch/closed result marshaling, stale suppression, close/clear invalidation, control restoration, refusal/failure, and single-flight apply regressions
- test_hygiene_scope.py — retired-persona registry/source removal, truthful OUT_OF_SCOPE classification/refusal, generic UNKNOWN, and non-delegation regressions
- test_healing_controller.py — C4-I1 pure-controller regressions: structural hard bound, deterministic termination states, write-ahead journal ordering, pre-iteration journal-failure blocking, uncertain post-execution journal failure, bounded/redacted observations, cancellation safe boundary, controller-owned timeouts, no-execution spy/AST proof, no-auto-apply proof, and determinism
- test_mcp_resource_core.py — D1-I1 pure admission regressions: HTTPS/IDNA/IPv6/origin pinning, private-host refusal, tools refusal, allowlisting/duplicates, fingerprint re-verification, bounds/redaction/truncation, transport normalization, revocation/readmission, result immutability/isolation, and no-I/O/dynamic-code purity
- Total discovery count is 507 (one expected Windows symlink-privilege skip)
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
