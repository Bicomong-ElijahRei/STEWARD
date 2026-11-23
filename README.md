# STEWARD
Desktop AI file organizer. A CustomTkinter "Mission Control" dashboard that routes natural
language requests across multiple LLM providers and executes sandboxed file operations with
preview, explicit approval, and undo/redo.

## What it actually does today
- Chat: Cortex classifies intent and routes to Foldy (file operations), Scout (semantic
  document search), Syntax (provider-backed coding text), or Cortex for general conversation.
- Cortex conversation: general chat retains at most 6 turns, 12,000 total characters, and
  4,000 characters per message. Clearing chat erases that memory and rejects stale responses.
- Syntax assistance: generation, debugging, refactoring, review, and explanation use providers
  bound to the Syntax role. Syntax is text-only: it has no file, process, or tool-execution surface.
- Scout RAG: persistent ChromaDB knowledge index with document ingestion, 500-character
  overlapping chunks, semantic retrieval, and source/content snippets in chat.
- File operations: preview a plan, approve it by ID, and execute exactly the approved plan.
  Preview generations own plan publication and provider metadata, so discarded or superseded
  previews cannot become executable or overwrite newer results.
- Organizer: per-file preview table with checkboxes, execute, undo/redo timeline, and
  restart-persistent scheduled scans with cooperative cancellation.
- Watchdog daemon: watches Incoming/, categorizes new files, moves them into Sorted/.
  Deduplication is filesystem-identity-aware, concurrency is capped at 4 workers and 32
  outstanding files, and stopping the daemon cancels queued work without holding process exit.
- API Hub: add/verify/discover providers, bind them to agent roles, enable/disable, and
  rotate one explicitly selected shared credential by ID with endpoint/link validation.
- Multi-provider routing with latency-based selection, 429 key failover on the same
  endpoint, 401/403 deactivation, 5xx cooldowns, and live failover visualization.

## Safety model
- All file operations are confined to <root>/Incoming and <root>/Sorted. Paths are resolved
  with realpath + commonpath + normcase; absolute paths and traversal cannot escape.
- Reads are sandboxed too, so credentials outside the sandbox cannot be exfiltrated.
- The dispatchable tool set is derived from the declared schema; undeclared tools
  (bulk move, temp cleanup, deletion suggestion) are unreachable from a model-issued plan.
- The whole plan is preflighted before the first mutation; unsafe plans abort atomically.
  Plan preflight rejects occupied destinations, duplicate targets, and file/directory target
  collisions in either plan order, while the mutation primitive rechecks collisions immediately
  before publication.
- Move, rename, and undo/redo publication never overwrite an occupied destination. Regular
  files are published through a same-directory temporary copy and an atomic no-overwrite
  reservation; Windows uses hard-link reservation when available and an `O_EXCL` fallback.
- The operation journal is write-ahead durable: intent is atomically persisted before a
  filesystem mutation and completion afterward. Write failures stop the operation or leave
  an explicit `uncertain` record for manual reconciliation rather than claiming success.
  No-op mutations are non-success history, verified destination rollback is ordinary failure,
  and unresolved partial state is `uncertain` and blocks blind undo/redo.
- Folder history records only directories actually created, with filesystem identity checks.
  Partial folder creation preserves that ownership evidence for recovery. Legacy folder records
  without ownership evidence are not destructively undone or redone.
- Approval is bound to a preview plan ID. Stale, superseded, or replayed plans are refused.
- Clearing chat advances a conversation epoch and invalidates pending or in-flight previews;
  stale preview, approval, execution, provider, and specialist UI continuations are discarded.
- Provider metadata is request-local, preventing concurrent requests from reporting each
  other's provider selection.
- API keys are encrypted at rest with Fernet; credential rotation updates only the selected
  credential after validating its endpoint and provider links, with transactional rollback.
- A rotating scan cannot overlap with its predecessor: cancellation is checked between file
  operations, and restarting creates an isolated generation whose old worker cannot commit
  state or notifications into the replacement.
- Syntax receives text-only provider requests and cannot mutate files or execute code.
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
259 unit tests covering sandbox enforcement, plan approval, router failover, undo/redo,
credential rotation/recovery, migration safety, daemon concurrency, generation-safe scheduled
scans, bounded Cortex memory, provider-backed text-only Syntax, RAG, GUI lifecycle, no-overwrite
filesystem publication, whole-plan collision preflight, partial-outcome journal truthfulness, and
durable journal recovery.

## Architecture
See ARCHITECTURE.md for the module map and critical request paths.
See PLAN.md for scope, status, and the roadmap.
See docs/MIGRATION_GUIDE.md for the guarded shared-credential migration workflow.
Use `python tools/migrate_live.py --dry-run` to preview; live mutation requires explicit
confirmation and a verified database/key/operation-log backup set.

## Known limitations
- Click (PC control) is a registered persona but is not implemented.
- Syntax produces suggestions as text; it does not edit files, run code, or apply patches.
- Scout searches a local `./rag_index/` knowledge base. Documents must be ingested through
  the RAG API; the first production search may download ChromaDB's MiniLM embedding model.
- GUI approval waits are bounded to 600 seconds. Live shared-credential migration confirmation
  is bounded to 300 seconds; timeout aborts before any live mutation.
- Sandbox roots are fixed to Incoming/ and Sorted/ under the working directory.
- Operation-history locking is process-local. Separate STEWARD processes can plausibly share
  the same `%APPDATA%\STEWARD\steward_operations.json`; cross-process journal ownership needs a
  separately reviewed locking design.
- No packaging/installer yet.

## Roadmap
v2.4 is complete. v3.0 has safe-intelligence foundations implemented (safe credential rotation,
generation-safe scheduling, bounded Cortex memory, lifecycle-owned previews, and text-only
Syntax with review/explanation intents); meta-prompting,
surgical file patches, self-healing execution, MCP, vision, voice, and remote control remain
future work tracked in PLAN.md.
