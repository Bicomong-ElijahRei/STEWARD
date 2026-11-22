# STEWARD
Desktop AI file organizer. A CustomTkinter "Mission Control" dashboard that routes natural
language requests across multiple LLM providers and executes sandboxed file operations with
preview, explicit approval, and undo/redo.

## What it actually does today
- Chat: a supervisor (Cortex) classifies intent and routes to the file agent (Foldy).
- File operations: preview a plan, approve it by ID, execute exactly the approved plan.
- Organizer: per-file preview table with checkboxes, execute, undo/redo timeline.
- Watchdog daemon: watches Incoming/, categorizes new files, moves them into Sorted/.
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
61 unit tests covering sandbox enforcement, plan approval, router failover, undo/redo
semantics, credential recovery, and GUI threading/lifecycle.

## Architecture
See ARCHITECTURE.md for the module map and the two critical request paths.
See PLAN.md for scope, status, and the roadmap.

## Known limitations (be honest here)
- Chat handles file-operation intents. Click (PC control), Scout (RAG), and Syntax (coding)
  are registered personas but not implemented; general conversation falls through to a
  canned response.
- Confirmation dialog waits are unbounded; an unanswered dialog blocks that worker thread.
- Sandbox roots are fixed to Incoming/ and Sorted/ under the working directory.
- Production data lives in the repo working directory; relocating it to %APPDATA% is planned.
- No packaging/installer yet.

## Roadmap
Phase B (UI motion), Phase C (agent swarm, AST patching, RAG), Phase D (MCP, vision, voice,
remote) are specified in PLAN.md as backlog, not implemented.
