# STEWARD
Desktop AI file organizer. A CustomTkinter "Mission Control" dashboard that routes natural
language requests across multiple LLM providers and executes sandboxed file operations with
preview, explicit approval, and undo/redo.

## What it actually does today
- Chat: Cortex classifies intent and routes to Foldy (file operations), Scout (semantic
  document search), Syntax (provider-backed coding text), or Cortex for general conversation.
  Requests for intentionally unsupported capabilities receive a truthful no-action refusal rather
  than delegation or an apparently available persona.
- Cortex conversation: general chat retains at most 6 turns, 12,000 total characters, and
  4,000 characters per message. Clearing chat erases that memory and rejects stale responses.
- Syntax assistance: generation, debugging, refactoring, review, and explanation use providers
  bound to the Syntax role. Syntax is text-only: it has no file, process, or tool-execution surface.
- Meta-prompting: in explicit **Plan first** mode for validated coding requests, Cortex writes a
  strict schema-validated plan artifact. After you approve that exact plan ID, a separate
  text-only Syntax request elaborates it. Neither step applies file changes. Implemented locally
  in commit `1c66ecb9`.
- Internal AST patch staging: a pure, I/O-free engine validates one strict Python patch artifact,
  resolves definition anchors, and stages byte-preserving replace/insert edits with a deterministic
  diff and exact unrelated-byte proof.
- Internal admitted patch replacement: a separate safety layer can replace exactly one explicitly
  selected `.py` file under a separately selected workspace using verified same-directory staging
  and `os.replace`, with durable journaling, exact backups, and hash-guarded undo/redo.
- User-integrated patch review: the Chat header's **Patch Review** control opens a workspace/target
  picker for the latest reviewed plan, generates a deterministic exact-diff preview, and requires a
  distinct epoch-bound, single-use approval before applying. Approvals bind the plan, workspace
  fingerprint, source/output hashes, exact-diff SHA-256, and immutable artifact SHA-256. Proposal
  and apply run off the Tk main thread in one bounded worker slot; closing the dialog or clearing
  chat invalidates the preview, closes the surface, and discards any late worker result.
- Scout RAG: persistent ChromaDB knowledge index with document ingestion, 500-character
  overlapping chunks, semantic retrieval, and source/content snippets in chat.
- Code context: an explicitly selected project root can be indexed in a separate persistent
  `steward_code` collection. Python AST symbols, bounded overlapping fallback chunks,
  path/line-aware retrieval, incremental replacement, status, and clear are available from
  the Chat header's **Code Index** control. Phase C7 also derives a static, read-only
  import/call graph and uses bounded root-scoped dependency expansion to include relevant
  cross-file snippets. Retrieved snippets are included in Syntax's existing text-only provider
  prompt.
- File operations: preview a plan, approve it by ID, and execute exactly the approved plan.
  Preview generations own plan publication and provider metadata, so discarded or superseded
  previews cannot become executable or overwrite newer results.
- Bounded filesystem reports: Foldy can request duplicate-file, large-file, and advisory deletion-
  candidate reports from Incoming/Sorted. The reports are deterministic, canonicalize paths, exclude
  symlinks/junctions, and enforce file-count, depth, result-count, serialized-byte, path-length,
  size-threshold, and age-threshold bounds. Duplicate hashing is bounded to 64 MiB per file and
  256 MiB per report, with stable file-identity checks around the read. Deletion suggestions never
  delete or schedule deletion.
- Bound bulk cleanup: Foldy exposes exactly two cleanup tools for temporary files and removable
  empty directories. The application enumerates and binds the exact candidate set, previews every
  path, and re-verifies the whole plan before removal. Removal uses the recycle bin only and
  cannot be undone; permanent bulk deletion is not exposed.
- Organizer: per-file preview table with checkboxes, execute, undo/redo timeline, and
  restart-persistent scheduled scans with cooperative cancellation.
- Watchdog daemon: watches Incoming/, categorizes new files, moves them into Sorted/.
  Deduplication is filesystem-identity-aware, concurrency is capped at 4 workers and 32
  outstanding files, and stopping the daemon cancels queued work without holding process exit.
- API Hub: add/verify/discover providers, bind them to agent roles, enable/disable, and
  rotate one explicitly selected shared credential by ID with endpoint/link validation. The
  non-streaming health check reports total completed-request elapsed time, not time to first
  byte or time to first token.
- Multi-provider routing with latency-based selection, 429 key failover on the same
  endpoint, 401/403 deactivation, 404/5xx/timeout/connection/invalid-JSON cooldowns, and live
  failover visualization. Persistent failures start the five-minute cooldown on the fourth failure.

## Safety model
- All file operations are confined to <root>/Incoming and <root>/Sorted. Paths are resolved
  with realpath + commonpath + normcase; absolute paths and traversal cannot escape.
- Reads are sandboxed too, so credentials outside the sandbox cannot be exfiltrated.
- The dispatchable tool set is derived from the declared schema and contains exactly twelve tools.
  The two cleanup tools accept only a sandboxed `directory`; application-owned binding supplies
  every candidate path. Any candidate-set or policy drift refuses the whole plan before removal.
  `send2trash` is the only removal primitive, and bulk cleanup is truthfully non-undoable.
  Deletion suggestions remain bounded advisory reports and never delete.
- The whole plan is preflighted before the first mutation; unsafe plans abort atomically.
  Plan preflight rejects occupied destinations, duplicate targets, and file/directory target
  collisions in either plan order, while the mutation primitive rechecks collisions immediately
  before publication.
- Move, rename, and undo/redo publication never overwrite an occupied destination. Regular
  files are published through a same-directory temporary copy and an atomic no-overwrite
  reservation; Windows uses hard-link reservation when available and an `O_EXCL` fallback.
- The operation journal is write-ahead durable: intent is atomically persisted before a
  filesystem mutation and completion afterward. A persistent `<operation-log>.lock` sidecar
  serializes journal access across STEWARD processes using an OS-managed exclusive lock, and
  the same lock covers the complete mutation or undo/redo transition lifecycle. Acquisition
  has a 10-second default timeout and fails closed before filesystem mutation if the lock cannot
  be acquired; the sidecar remains reusable after process termination. Write failures stop the
  operation or leave an explicit `uncertain` record for manual reconciliation rather than
  claiming success. No-op mutations are non-success history, verified destination rollback is
  ordinary failure, and unresolved partial state is `uncertain` and blocks blind undo/redo.
- Folder history records only directories actually created, with filesystem identity checks.
  Partial folder creation preserves that ownership evidence for recovery. Legacy folder records
  without ownership evidence are not destructively undone or redone.
- Approval is bound to a preview plan ID. Stale, superseded, or replayed plans are refused.
- Clearing chat advances a conversation epoch and invalidates pending or in-flight previews;
  stale preview, approval, execution, provider, specialist, and Patch Review worker UI
  continuations are discarded.
- Provider metadata is request-local, preventing concurrent requests from reporting each
  other's provider selection.
- API keys are encrypted at rest with Fernet; credential rotation updates only the selected
  credential after validating its endpoint and provider links, with transactional rollback.
- A rotating scan cannot overlap with its predecessor: cancellation is checked between file
  operations, and restarting creates an isolated generation whose old worker cannot commit
  state or notifications into the replacement.
- Syntax receives text-only provider requests and cannot mutate files or execute code.
- The internal AST patch staging engine accepts already-admitted bytes only. It rejects duplicate
  JSON keys, malformed schemas/paths/anchors, overlapping edits, invalid encodings, and oversized
  artifacts; preserves BOM/newline mode and final-newline state; and proves bytes outside edited
  ranges are identical. It does not read/write files, resolve workspace paths, approve or persist
  patches, import/execute targets, lint, test, or mutate source.
- The separate C3-I2 replacement layer admits exactly one existing `.py` file under an explicitly
  selected workspace. It rejects traversal, non-Python/denied paths, symlink/junction/reparse
  components, non-regular files, unsafe roots, and sources over 1 MiB. It revalidates source
  identity/hash and engine proofs before a same-directory verified `os.replace`; persists journal
  intent before the mutation and completion afterward; stores exact pre/post bytes outside the
  workspace; and permits only hash-guarded undo/redo. Uncertain edits block blind recovery.
  Target code is never executed, imported, linted, or tested.
- C3-I3 adds an immutable, write-once exact-diff artifact and a separate single-use approval.
  The approval binds the conversation epoch, reviewed plan ID, canonical workspace fingerprint,
  relative target, source/output SHA-256 values, exact-diff SHA-256, and artifact SHA-256.
  Changed source, workspace, artifact, diff, reviewed plan, or epoch refuses before mutation;
  approval IDs cannot be replayed; journal-lock contention fails closed; and a failed apply clears
  pending proposal/approval state.
- Code indexing is read-only: it never imports or runs indexed source, denies secret/key/
  database/state paths and dependency caches, refuses symlink/junction targets outside the
  selected root, and bounds traversal to 2,000 files and 256 KiB per file. The local index
  stores plaintext chunks; retrieved snippets are sent to the configured Syntax provider
  (cloud-first unless explicitly configured otherwise).
- Undo/redo only records verified success and refuses to overwrite existing files.

## Install
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
Python 3.12. Persistent configuration lives in `%APPDATA%\STEWARD\steward.db`; its Fernet
key lives beside it as `secret.key`. Legacy repository-root files are copied, not moved, on
first startup. Back up the AppData database/key pair; they are not recoverable from the repo.

## Tests
```
python -m unittest discover -v
python test_validator.py
```
572 unit tests covering sandbox enforcement, plan approval, router failover (including persistent
HTTP 404 accounting), undo/redo, credential rotation/recovery, migration safety, daemon
concurrency, generation-safe scheduled scans, bounded Cortex memory, provider-backed text-only
Syntax, document RAG, bounded read-only code indexing/retrieval and static dependency-graph
expansion, GUI lifecycle, no-overwrite filesystem publication, whole-plan collision preflight,
partial-outcome journal truthfulness, durable journal recovery, cross-process journal serialization,
strict bounded read-only filesystem reports, bounded duplicate hashing, bulk-cleanup
enumeration/exact-set binding/typed drift refusal/recycle-bin-only execution/truthful non-undoable
journal semantics, schema-validated meta-prompting review gates,
pure AST patch artifact/anchor/splicing/
encoding/proof/determinism/purity safety, C3-I2 workspace admission, atomic replacement,
journal/backup, and guarded content recovery, C3-I3 exact-diff review, immutable artifact,
single-use approval, lifecycle invalidation, mutation refusal, and guarded real-file apply,
Patch Review off-main worker/epoch/close/clear/single-flight behavior, truthful removed-scope
refusal,
and the C4-I1 pure iteration controller's hard bound, termination, journal, observation,
cancellation, no-execution, and no-auto-apply guarantees, plus persistent ChromaDB client
reinitialization, rollback, close-failure, and Windows file-handle release behavior.

## Architecture
See ARCHITECTURE.md for the module map and critical request paths.
See PLAN.md for scope, status, and the roadmap.
See docs/MIGRATION_GUIDE.md for the guarded shared-credential migration workflow.
See docs/bulk_deletion_contract.md for bulk-cleanup decisions, exact-set binding, and execution contract.
Use `python tools/migrate_live.py --dry-run` to preview; live mutation requires explicit
confirmation and a verified database/key/operation-log backup set.

## Known limitations
- Screen-aware desktop automation, voice control, and phone/remote control remain outside declared scope. Their retired persona and routing surfaces have been removed; such requests are refused as out of scope rather than delegated.
- Syntax produces suggestions as text; it does not edit files, run code, or apply patches.
- Patch Review applies only one explicitly selected Python file in an explicitly selected
  workspace, never executes or tests the target, and does not yet support multi-file patches,
  deletion edits, lint/run loops, or automatic self-healing.
- Self-healing is not user-integrated. Only a pure, bounded iteration controller exists
  (`agents/healing_controller.py`): it has no executor, no sandbox, no GUI wiring, no process
  or shell surface, and it cannot apply patches — it can only request that a proposal enter
  the existing Patch Review approval gate. Real lint/run execution stays backloged until an
  OS-level isolation boundary is selected and proven.
- Plan first produces an approval-gated plan and text-only elaboration; Patch Review is a
  separate explicit exact-diff workflow bound to the latest reviewed plan ID.
- Scout searches a local `./rag_index/` knowledge base. Documents must be ingested through
  the RAG API; the first production search may download ChromaDB's MiniLM embedding model.
- Code context retrieves symbol-sized semantic snippets and statically derived import/call
  dependency context. Graph resolution is a name-based approximation: dynamic imports, aliases,
  ambiguous symbols, and runtime dependency behavior are not resolved. The local
  `steward_code` collection contains plaintext source excerpts, and the GUI discloses that
  retrieved excerpts are sent to the configured provider.
- GUI approval waits are bounded to 600 seconds. Live shared-credential migration confirmation
  is bounded to 300 seconds; timeout aborts before any live mutation.
- Sandbox roots are fixed to Incoming/ and Sorted/ under the working directory.
- Bulk destructive filesystem utilities (`cleanup_temp_files`, `cleanup_empty_folders`, and
  `batch_move`) are intentionally outside the active FileAgent schema and remain backlog-only.
  BULK-1 adds only an internal, read-only enumeration/set-binding core; it exposes no destructive
  operation or new chat capability. A future destructive implementation is intended to use
  `send2trash` and requires a separately reviewed approval/execution path; permanent bulk removal
  is not being exposed. The legacy `agent/core.py` `StewardAgent` is non-authoritative and has no
  runtime callers; the active `agents/file_agent.py` is the provider/dispatch authority.
- Cross-process journal locking is implemented and validated on Windows. The POSIX
  `fcntl.flock` path is present but has not been locally validated on this Windows host.
- No packaging/installer yet.

## Roadmap
v2.4 is complete. v3.0 has safe-intelligence foundations implemented (safe credential rotation,
generation-safe scheduling, bounded Cortex memory, lifecycle-owned previews, text-only
Syntax with review/explanation intents, bounded read-only code-context retrieval with
static dependency expansion, pure AST patch staging, admitted one-file replacement/recovery,
and a user-integrated exact-diff Patch Review workflow); self-healing execution and MCP remain
future work tracked in PLAN.md. Voice control, phone/remote control, and screen-aware
automation were removed from declared scope and remain recorded in PLAN.md and ROADMAP.md.
The orphaned active persona/routing surfaces were subsequently removed; unsupported requests
now receive a truthful no-action refusal.
The C4-I1 pure iteration controller is landed but not user-integrated and deliberately exposes
no execution surface.
