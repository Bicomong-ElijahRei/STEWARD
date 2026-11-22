# STEWARD
Desktop AI file organizer. A CustomTkinter "Mission Control" dashboard that routes natural
language requests across multiple LLM providers and executes sandboxed file operations with
preview, explicit approval, and undo/redo.

## What it actually does today
- Chat: a supervisor (Cortex) classifies intent and routes to the file agent (Foldy)
  or semantic search agent (Scout).
- Scout RAG: persistent ChromaDB knowledge index with document ingestion, 500-character
  overlapping chunks, semantic retrieval, and source/content snippets in chat.
- File operations: preview a plan, approve it by ID, execute exactly the approved plan.
- Organizer: per-file preview table with checkboxes, execute, undo/redo timeline.
- Watchdog daemon: watches Incoming/, categorizes new files, moves them into Sorted/.
  Deduplication is filesystem-identity-aware, concurrency is capped at 4 workers and 32
  outstanding files, and stopping the daemon cancels queued work without holding process exit.
- API Hub: add/verify/discover providers, bind them to agent roles, enable/disable.
- Multi-provider routing with latency-based selection, 429 key failover on the same
  endpoint, 401/403 deactivation, 5xx cooldowns, and live failover visualization.

## Safety model
- All file operations are confined to <root>/Incoming and <root>/Sorted. Paths are resolved
  with realpath + commonpath + normcase; absolute paths and traversal cannot escape.
- Reads are sandboxed too, so credentials outside the sandbox cannot be exfiltrated.
- The dispatchable tool set is derived from the declared schema; undeclared tools
  (bulk move, temp cleanup, deletion suggestion) are unreachable from a model-issued plan.
- The whole plan is preflighted before the first mutation; unsafe plans abort atomically.
- Approval is bound to a preview plan ID. Stale, superseded, or replayed plans are refused.
- API keys are encrypted at rest with Fernet; a rotated/missing key degrades to a visible
  recoverable state rather than crashing or substituting wrong plaintext.
- Undo/redo only records verified success and refuses to overwrite existing files.

## Install
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
Python 3.12. Configuration lives in steward.db (encrypted); secret.key is generated on first
run. Both are gitignored — back them up, they are not recoverable from the repo.

## Tests
```
python -m unittest discover -v
python test_validator.py
```
138 unit tests covering sandbox enforcement, plan approval, router failover, undo/redo
semantics, credential recovery, migration safety, daemon concurrency, RAG ingestion/retrieval,
and GUI threading/lifecycle.

## Architecture
See ARCHITECTURE.md for the module map and critical request paths.
See PLAN.md for scope, status, and the roadmap.
See docs/MIGRATION_GUIDE.md for the guarded shared-credential migration workflow.
Use `python tools/migrate_live.py --dry-run` to preview; live mutation requires explicit
confirmation and a verified database/key/operation-log backup set.

## Known limitations
- Click (PC control) and Syntax (coding) are registered personas but not implemented;
  general conversation falls through to a canned response.
- Scout searches a local `./rag_index/` knowledge base. Documents must be ingested through
  the RAG API; the first production search may download ChromaDB's MiniLM embedding model.
- GUI approval waits are bounded to 600 seconds. Live shared-credential migration confirmation
  is bounded to 300 seconds; timeout aborts before any live mutation.
- Sandbox roots are fixed to Incoming/ and Sorted/ under the working directory.
- Production data lives in the repo working directory; relocating it to %APPDATA% is planned.
- No packaging/installer yet.

## Roadmap
Phase C5 (RAG) is implemented; Phase C swarm/AST work and Phase D (MCP, vision, voice,
remote) remain backlog in PLAN.md.
