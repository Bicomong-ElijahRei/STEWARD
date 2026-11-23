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
- Meta-prompting: in explicit **Plan first** mode for validated coding requests, Cortex writes a
  strict schema-validated plan artifact. After you approve that exact plan ID, a separate
  text-only Syntax request elaborates it. Neither step applies file changes. Implemented locally
  in commit `1c66ecb9`.
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
  stale preview, approval, execution, provider, and specialist UI continuations are discarded.
- Provider metadata is request-local, preventing concurrent requests from reporting each
  other's provider selection.
- API keys are encrypted at rest with Fernet; credential rotation updates only the selected
  credential after validating its endpoint and provider links, with transactional rollback.
- A rotating scan cannot overlap with its predecessor: cancellation is checked between file
  operations, and restarting creates an isolated generation whose old worker cannot commit
  state or notifications into the replacement.
- Syntax receives text-only provider requests and cannot mutate files or execute code.
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
316 unit tests covering sandbox enforcement, plan approval, router failover, undo/redo,
credential rotation/recovery, migration safety, daemon concurrency, generation-safe scheduled
scans, bounded Cortex memory, provider-backed text-only Syntax, document RAG, bounded
read-only code indexing/retrieval and static dependency-graph expansion, GUI lifecycle,
no-overwrite filesystem publication, whole-plan collision preflight, partial-outcome journal
truthfulness, durable journal recovery,
cross-process journal serialization, and schema-validated meta-prompting review gates.

## Architecture
See ARCHITECTURE.md for the module map and critical request paths.
See PLAN.md for scope, status, and the roadmap.
See docs/MIGRATION_GUIDE.md for the guarded shared-credential migration workflow.
Use `python tools/migrate_live.py --dry-run` to preview; live mutation requires explicit
confirmation and a verified database/key/operation-log backup set.

## Known limitations
- Click (PC control) is a registered persona but is not implemented.
- Syntax produces suggestions as text; it does not edit files, run code, or apply patches.
- Plan first produces an approval-gated plan and text-only elaboration only; it does not apply
  the plan. Automated application remains Phase C3.
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
- Cross-process journal locking is implemented and validated on Windows. The POSIX
  `fcntl.flock` path is present but has not been locally validated on this Windows host.
- No packaging/installer yet.

## Roadmap
v2.4 is complete. v3.0 has safe-intelligence foundations implemented (safe credential rotation,
generation-safe scheduling, bounded Cortex memory, lifecycle-owned previews, text-only
Syntax with review/explanation intents, and bounded read-only code-context retrieval with
static dependency expansion); surgical file patches, self-healing execution, MCP, vision,
voice, and remote control remain future work tracked in PLAN.md.
