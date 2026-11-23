# STEWARD v2 — Executable Work Plan (living document)

Read ARCHITECTURE.md first. This file is the ONLY source of truth for scope and status.
Chat logs, memories, and verbal plans are not. If this file and the code disagree:
the code wins on behavior, this file wins on intent — fix this file in the same commit.

## Amendment protocol (how this document changes)
1. Statuses: OPEN | IN-PROGRESS | DONE | DISPUTED | DEFERRED. DONE requires a commit SHA.
2. Add, remove, split, re-scope, or re-estimate ANY item by editing this file directly.
3. Every structural change gets ONE changelog line: date | HEAD | change | why.
4. No silent scope growth: an item discovered mid-batch moves to a new batch or the
   backlog FIRST, then is worked. (This rule exists because a session once invented
   "Item 5" and padded a report with it.)
5. Estimates are bands, not promises. When reality differs, revise the band and log it.
   Being wrong is fine; being silently wrong is not.
6. The freeze line moves only by explicit owner decision, logged in the changelog.
7. Items may be DEFERRED forever without shame. Deferred is a decision, not a failure.

## Changelog
2026-11-23 | cc4800de | Activated FS-S5 with an explicit portable cross-process journal-lock design, bounded timeout, crash-release semantics, transition-claim requirements, and isolated multi-process regression plan. | Separate STEWARD processes can share the AppData operation log, so process-local synchronization is insufficient.
2026-11-23 | e1a37c30 | Filesystem journal truthfulness: distinguish no-op, failed, and uncertain outcomes; preserve partial-folder ownership evidence; detect file/directory plan conflicts in either order; 259/259 unit tests green. | Make durable history reflect unresolved filesystem state and prevent conflicting whole plans from mutating disk.
2026-11-23 | 9d092fd7 | Added Batch FS-SAFETY-1: reproduce and repair no-op, partial-mutation, partial-folder, and folder-target preflight journal truthfulness; defer cross-process journal locking pending reviewed design. | Reproduce the handoff leads against the current checkout before changing safety behavior.
2026-11-23 | 7907ebb1 | Filesystem mutation safety: added no-overwrite publication, write-ahead atomic operation history, exact folder ownership, whole-plan destination conflict preflight, uncertain-state recovery, and 247/247 unit tests green.
2026-11-23 | 8dd2e411 | Lifecycle hardening: added preview-generation ownership, epoch-guarded chat/approval/execution/specialist UI continuations, five Syntax intents, and generation-isolated scanner restarts; 236/236 unit tests green.
2026-11-23 | 8dd2e411 | Documentation reconciliation: updated README, ARCHITECTURE, PLAN, and ROADMAP to match the implemented credential, scheduler, conversation, Syntax, AppData, lifecycle, provider-attribution, and test state; 236/236 unit tests green.
2026-11-23 | 410cbdcf | v3.0 safe-intelligence foundations: added explicit shared-credential rotation, generation-safe scheduled scans, bounded Cortex conversation memory with stale-response rejection, and provider-backed text-only Syntax assistance; 192/192 unit tests green.
2026-11-23 | 61390dca | Credential rotation safety: rotation now targets one explicit credential ID, validates the normalized endpoint and provider links, and rolls back failed updates; 180/180 unit tests green.
2026-11-23 | 518785a9 | Scheduled-scan lifecycle: generation-specific cancellation, active-scan tracking, bounded stop, and restart refusal while old work remains alive; 184/184 unit tests green.
2026-11-23 | 9641d1f1 | Cortex conversation memory: bounded to 6 turns, 12,000 total characters, and 4,000 characters per message; clear-chat invalidates stale in-flight responses.
2026-11-23 | 410cbdcf | Syntax assistance: provider-backed generation/debug/refactoring is routed as text-only requests and cannot mutate files or execute code.
2026-11-23 | b99c9a38 | Persistent state moved to `%APPDATA%\STEWARD` with copy-only, non-overwriting migration of legacy database/key/operation-log files; 180/180 unit tests green.
2026-11-23 | 7d9d25c6 | v2.4 compatibility gate: removed unsupported CTkOptionMenu hover_color for CustomTkinter 5.2.2, strengthened the scheduled-scan UI regression check, and verified a clean bounded GUI startup; 175/175 unit tests green.
2026-11-23 | 37f03ba2 | v2.4 Hierarchical Swarm & Scheduling: added readable plain-text Markdown chat rendering, bounded Cortex-to-specialist delegation with failure isolation and Live Feed observability, and restart-persistent recurring file scans with Organizer controls; 175/175 unit tests green.
2026-11-23 | f1d98141 | P2 Learning Module: added deterministic priority-ordered rules.yaml categorization, pre-LLM Foldy bypass, manual override learning, Organizer rule display, and `[Rule]` chat labeling; 153/153 unit tests green.
2026-11-23 | e3ae8871 | Phase C5 RAG integration: persistent ChromaDB ingestion/chunking/embedding/retrieval, source-change replacement, recursive document ingestion, deterministic Scout routing, and Chat search results; 138/138 unit tests green.
2026-11-23 | 2b9e5031 | Snoop & Fix pass 5: closed credential/provider lifecycle gaps, marked bounded file previews, hardened category sanitization, added bounded supervisor FILE_OP follow-up context, invalidated stale organizer previews, exposed live-feed clearing, and widened responsive constellation bounds; 127/127 unit tests green.
2026-11-23 | 58ac00f4 | Snoop & Fix pass 4: daemon now has identity-aware dedup, 4 workers/32 outstanding files, stop-responsive backpressure, and daemon-thread lifecycle; migration preserves valid shared links and bounds confirmation; 115/115 unit tests green.
2026-11-23 | 049891af | Snoop & Fix pass 3: bounded daemon concurrency, hardened migration wrapper/workflow, and regression coverage; 113/113 unit tests green.
2026-11-23 | 24da229e | Snoop & Fix pass 2: GUI rendering/lifecycle hardening and organizer flow fixes; 106/106 unit tests green.
2026-11-23 | a11d14f5 | Snoop & Fix pass 1: routing, sandbox, credential recovery, and helper hardening; 99/99 unit tests green.
2026-11-22 | 016d336d | Reconciled state: fixed helpers.py imports, confirmed the single categorise_file and test class definitions, added duplicate-definition regression guards, and verified 90/90 unit tests green; Phase B 5/5 items done.
2026-11-22 | d2687aec | B3 Live Constellation View implemented with stable responsive layout, live agent states, SafeTick cleanup, and 88/88 unit tests green.
2026-11-22 | 2df98d09 | tools/migrate_live.py added; guarded live dry-run/execute/rollback with verified backups; 4/4 CLI tests green.
2026-11-22 | b59b7c30 | Reconciled state: Phase B 4/5 items done; 85 unit tests green.
2026-11-22 | ab585a7f | tools/run_migration.py added; Batch 4c fully closed.
2026-11-22 | eef11f9b | Batch 4c closed: shared credential store live; 72/72 green.
2026-11-22 | 535b9c6d | Batch 4c first push carried a syntax break from a partial replace; repairs applied locally, gate pending.
2026-11-22 | 5357cc43 | Batch 4b closed: credential store safety review committed (docs/credential_store_review.md).
2026-11-22 | 3f0ed7d1 | Batch 4a closed: bounded dialog waits (L2 fully closed) and strengthened dedup test; 62 tests green.
2026-11-22 | 33e2b281 | v2.0 FROZEN. README shipped. (amends 1a538464)
2026-11-22 | 7f682d6d | PLAN state repair; app smoke-tested live (failover observed end-to-end); credential store queued to v2.1.
2026-11-22 | b80d2933 | Emergency DB recovery: steward.db restored from C:\temp\db_data.json (16 providers, 4 traces), 16/16 keys decrypted. Invariant corrected: hashes MAY change. Cause: an agent deleted the DB trying to force a hash match.
2026-11-21 | a4408e7f | Document created. Batch 1 (H1,H2,H3,H4,H7) closed and verified.
(future entries above this line, newest first)

## Ground state
Implementation baseline: FS-S5 implementation commit pending local closure
Suite: 266/266 unit tests green; validator 5/5; compileall and diff checks green
Persistent state: `%APPDATA%\STEWARD`; legacy repository-root files are copied, never moved or overwritten.
Invariants: The agent must never write to, delete, or recreate steward.db or secret.key. Their hashes MAY change during normal application use; a changed hash is NOT a defect; helper scripts never in repo.
Tool split: Qwen agent-mode sandbox proves safety fixes off-tree; human applies + verifies; Cline/Kimi/Antigravity for volume. Never two writers on one file.

## Implemented
- v3.0 Safe-Intelligence Foundations — DONE | 61390dca, 518785a9, 9641d1f1, 410cbdcf, 7907ebb1, e1a37c30
  explicit shared-credential rotation; generation-safe scheduled scans; bounded Cortex
  general-chat memory with stale-response rejection; provider-backed text-only Syntax across
  generation/debugging/refactoring/review/explanation; generation-owned file previews with
  epoch-guarded approval/execution/provider/specialist continuations; no-overwrite
  filesystem publication with durable write-ahead operation history; truthful no-op/failed/
  uncertain journal outcomes; and whole-plan file/directory conflict detection.
  Proof: 266/266 unit tests green, including cross-process journal serialization.
- Persistent state relocation — DONE | b99c9a38 | Database, Fernet key, and operation log
  use `%APPDATA%\STEWARD`; legacy root files are copied without overwrite and the legacy
  sources remain intact. Proof: AppDataMigrationTests.
- v2.4 Hierarchical Swarm & Scheduling — DONE | 37f03ba2, 7d9d25c6 | Markdown chat
  rendering, bounded observable Cortex delegation, and persistent recurring file scans.
  Proof: MarkdownRenderingTests, HierarchicalSwarmTests, and ScheduledScannerTests;
  175/175 unit tests green; compile and bounded GUI startup gates passed.
- P2 Learning Module (rules.yaml) — DONE | f1d98141 | deterministic
  priority-ordered filename rules load from and persist to YAML; known patterns bypass
  the Foldy LLM categorization request; rule targets are sanitized before folder
  creation; manual overrides can learn a regex rule; the Organizer tab exposes the
  current rules; and rule-based chat results are marked `[Rule]`. Proof:
  RulesEngineTests cover bypass, fallback, priority, persistence, learning, sanitization,
  UI display, and chat labeling; 153/153 unit tests green.

## Freeze line
v2.0 FROZEN as of 33e2b281. All remediation and housekeeping closed.
v2.1 closed: 4a, 4b, and 4c complete. v2.2 Visuals & RAG complete through C5. v2.3 Learning & Rules closed at f1d98141. v2.4 Hierarchical Swarm & Scheduling closed at 7d9d25c6. v3.0 safe-intelligence foundations current through the filesystem journal-truthfulness baseline e1a37c30. New findings go to the backlog.

## BATCH FS-SAFETY-1 — filesystem journal truthfulness and plan conflicts
Files: agent/tools.py, agents/file_agent.py, test_filesystem_journal_hardening.py, ARCHITECTURE.md, README.md, PLAN.md
- FS-S1  DONE | e1a37c30 | Same-name rename returns `no_op` but was journaled as a
      successful reversible operation. Accept: the file is unchanged; no successful rename
      history entry exists; the no-op does not prevent undo of the preceding legitimate move.
- FS-S2  DONE | e1a37c30 | A published move/rename whose source removal fails may leave
      both source and destination, but the journal records ordinary failure. Accept: verified
      rollback records `failed`; unresolved cleanup records `uncertain` and blocks blind undo/redo;
      deterministic move and rename tests assert both filesystem and journal state.
- FS-S3  DONE | e1a37c30 | Folder creation loses created-directory evidence when a later
      component fails. Accept: a pre-change failure records ordinary failure; partial creation
      preserves exact created paths/ownership and records `uncertain`; deterministic tests assert
      the remaining tree and recovery state.
- FS-S4  DONE | e1a37c30 | Whole-plan preflight omitted `create_folder` targets. Accept:
      folder/move and folder/rename target conflicts are rejected in either plan order before
      any mutation; valid non-conflicting parent/child plans remain accepted.
- FS-S5  DONE | cc4800de | The operation journal uses process-local `threading.RLock`
      objects, and the application does not enforce one running instance, so separate STEWARD
      processes can plausibly update the same `%APPDATA%\STEWARD\steward_operations.json`.
      Implemented design: a stable persistent `<operation-log>.lock` sidecar with an OS-managed
      exclusive lock (`msvcrt.locking` on Windows, `fcntl.flock` on POSIX), plus the keyed
      in-process `RLock`; bounded 10-second timeout; sidecar never deleted. The cross-process lock
      covers the complete journal read/merge/revision-check/atomic-replace section and the complete
      write-ahead mutation / undo-redo claim, filesystem action, and completion sequence. The OS
      releases the lock on normal exit and process termination; acquisition timeout or lock API
      failure fails closed before mutation. Alternatives rejected: PID/stale-owner files need
      unsafe stale-lock recovery, directory locks do not provide ownership, and third-party locking
      packages add an unnecessary dependency.
      Accept: deterministic separate-process contention preserves every independently recorded
      operation; competing undo/redo claims cannot both mutate the filesystem; a held lock times
      out without mutation; process death releases the lock while the persistent sidecar remains
      reusable; journal write/replace failures preserve truthful recoverable state.
      Test plan: subprocess-based tests using temporary directories and one temporary operation-log
      path, with bounded waits and visible exit codes/timeouts; cover concurrent operations,
      exclusive undo/redo claims, timeout, crash release, and journal replace failure. Validate on
      the current Windows host; POSIX implementation is documented but not claimed as locally tested.
      Proof: Windows subprocess regressions pass; 266/266 discovery tests, 5/5 validator checks,
      compileall, and diff checks are green. The final implementation SHA is recorded in the
      changelog and closure entry below.

## BATCH 2A — router / database / settings / chat lifecycle
Files: core/router.py, core/database.py, gui/settings_tab.py, gui/chat_tab.py
- H5  DONE | fb6f876e | Router same-endpoint 429 preference reassigns the loop variable: skips a
      candidate, double-hits the promoted one; a HEALTHY provider can go unused and the
      whole request fails. Accept: each provider attempted <=1x per request, none skipped,
      in-request cooldown respected, failovers deduplicated. Proof: 3-provider test where
      the promoted candidate ALSO fails; assert third attempted, no double calls, no dup
      failovers.
- M4  DONE | fb6f876e | _decrypt has no InvalidToken handling; rotated key bricks routing + API Hub.
      Plus init_db ignores changed key_path; close() leaves stale singleton.
      Accept: recoverable error state, provider list still renders, never wrong plaintext.
- M5  DONE | fb6f876e | Re-verify upserts assigned_agent from form default "Any", unbinding the role.
      Accept: binding preserved unless explicitly changed; form pre-fills stored value.
- L1  DONE | fb6f876e | "Click" missing from dropdown; tier filter uses exact equality vs stored
      validator labels. Accept: Click bindable; tier matching matches stored labels.
- N1  DONE | fb6f876e | ChatTab finally calls self.after from worker with no lifecycle guard.
      Accept: destroyed-widget path raises nothing.
- N2  DONE | fb6f876e | send_chat has no in-flight flag; programmatic caller can double-run.
      Accept: two rapid sends produce one worker.
- N4  DONE | fb6f876e | execute_pending_plan raises for no-plan but returns str for stale/None.
      Accept: one uniform, documented refusal contract.
- N5  DONE | fb6f876e | ChatTab reads private file_agent._pending_plan_id. Accept: public accessor.

## BATCH 2B — recovery: undo/redo, operation log, schema
Files: agents/file_agent.py (gui/organizer_tab.py only if provably broken)
- H6  DONE | dfab67e9 | Undo marked delete / non-empty folder / unknown op as undone (false
      success). Fixed: state changes only on verified success; delete and unknown ops are
      skipped without mutation. NOTE: forward iteration in redo is CORRECT and was kept —
      the original "FIFO not LIFO" diagnosis was wrong. Do not "fix" this.
- M6  DONE | dfab67e9 | Log non-atomic write; ids are timestamps (not unique); no collision check
      before undo/redo move (silent overwrite on POSIX); no list validation on load.
      Accept: atomic writes, stable unique ids, explicit collision refusal, tolerant load.
      Backward-compat REQUIRED: legacy timestamp-id entries must still load.
- M1  DONE | dfab67e9 | undo_last/redo_last declared AND in allowlist but absent from tool_functions
      -> "Unknown tool". Accept: declared schema and dispatch set agree. CAUTION: _lock is
      NOT reentrant; include lock-ownership analysis and a timeout-guarded test if wired.
- N3  DONE | dfab67e9 | Preview asks approval for a plan that will be rejected. Accept: preview flags
      doomed operations, executes nothing during dry_run, execution preflight unchanged.

## BATCH 3 — daemon, threading, hygiene
- M2  DONE | 8d22ea78 | Daemon never moves files (dry_run); 0.5s sleep is not a stability check; dedup
      set cleared wholesale at 1000; observer not stopped on quit.
- M3  DONE | 8d22ea78 | Shared file_agent.dry_run mutated across surfaces. Accept: per-call mode.
- M7  DONE | 77c9a3b2 | find_duplicates reads whole files. Accept: chunked streaming hash.
- M8  DONE | 8d22ea78 | Organizer builds FilePreviewRow + BooleanVar on worker thread; pending_
      operations mutated from worker. Accept: construction and mutation on main thread.
- N6  DONE | 8d22ea78 | Daemon dest_base vs hardcoded sandbox roots. Accept: reconciled, documented.
- L2  DONE | 3f0ed7d1 | _scroll_chat guarded (77c9a3b2); evt.wait()/exec_evt.wait() in
      gui/chat_tab.py now timeout; worker exits cleanly and restores input on no answer.
- L3  DONE | 8d22ea78 | quit_app calls root.quit() from pystray thread; WM_DELETE overwritten;
      observer not stopped. Accept: one coherent marshaled shutdown path.
- L4  DONE | 77c9a3b2 | Untrack __pycache__/, .vscode/, Sorted media (keep on disk). The large .mkv is
      an OWNER decision (copyright/bloat). NO history rewrite without explicit approval.

## Housekeeping (v2.0)
- .clineignore  DONE | 036b6403 | create + commit; blocks secret.key/.env/*.db/media, NOT Sorted/ wholesale
- .clinerules   DONE | 036b6403 | commit (already authored)
- README.md     DONE | 33e2b281 | repo description, capabilities, safety model, install, tests, honest limitations

## BATCH 4a — v2.1 quick wins
- L2 remainder (bounded dialog waits)   DONE | 3f0ed7d1
- Dedup test strengthening (real __init__, retention AND boundedness) DONE | 3f0ed7d1

## BATCH 4b — credential store safety review
- docs/credential_store_review.md  DONE | 5357cc43 | schema, migration, rollback, backup, crypto impact, blast radius, failure modes, UI impact, security review, test plan. No code.

## BATCH 4c — shared credential store implementation (CLOSED)
Files: core/database.py, gui/settings_tab.py, core/discovery.py, test_phase0_phase_a.py, tools/run_migration.py, tools/migrate_live.py, docs/MIGRATION_GUIDE.md
Review doc: docs/credential_store_review.md
- Schema, dual-read, FK enforcement        DONE | eef11f9b
- migrate/rollback (idempotent, decrypt-grouped) DONE | eef11f9b
- API Hub shared-credential UI             DONE | eef11f9b
- CredentialStoreTests (10)                DONE | eef11f9b
- .clineignore backup patterns (*.backup/*.bak/*.sql) DONE | eef11f9b
- tools/run_migration.py (operator dry-run) DONE | ab585a7f
- tools/migrate_live.py (guarded dry-run/execute/rollback) DONE | 2df98d09
- MigrationCLITests (4 isolated subprocess tests) DONE | 2df98d09
Design notes: credentials NOT unique per endpoint (multi-key per endpoint is the feature);
add_provider reuses a credential only on decrypted-key match, else creates a new row;
set_credential upserts the canonical credential (rotation); migration groups by DECRYPTED
key (Fernet nonces make raw blobs distinct) and is idempotent; get_credential_by_url prefers
credentials linked to active providers ordered by speed_score_ms; fail-fast when DB exists
without secret.key is permanent policy.
Closure: shared credential store, operator migration tools, migration guide, and isolated
CLI coverage are committed. Snoop & Fix pass 4 preserves already-valid shared credential
links during idempotent migration and bounds live terminal confirmation to 300 seconds;
115/115 unit tests and 5/5 validator checks green.

## SNOOP & FIX — five-pass quality sweep (CLOSED)
- Pass 1 DONE | a11d14f5 | Core routing, sandbox, credential recovery, and helper hardening; 99/99 green.
- Pass 2 DONE | 24da229e | GUI rendering/lifecycle and organizer flow hardening; 106/106 green.
- Pass 3 DONE | 049891af | Bounded daemon workers/pending files, explicit daemon stop, guarded migration
  workflow, and migration safety regressions; 113/113 green.
- Pass 4 DONE | 58ac00f4 | Identity-aware recreated-path processing, daemon-thread lifecycle that cannot
  hold process exit, total outstanding-file invariant, shared-link preservation, bounded migration
  confirmation, and documentation reconciliation; 115/115 green.
- Pass 5 DONE | 2b9e5031 | Credential/provider deletion lifecycle, explicit bounded-preview markers,
  robust category sanitization, bounded supervisor FILE_OP follow-up context, organizer preview
  invalidation, visible live-feed clearing, and responsive constellation bounds; 127/127 green.

## PHASE B — Cyber-Kawaii Experience (WHAT only; visual, needs your eyes)
Gate: v2.0 frozen. All items: animations must not block the main thread and must raise
nothing when the window closes mid-animation (depends N1/N2 closed).
- B1  DONE | b59b7c30 | Four-state chat bubbles (THINKING/TOOL_USE/STREAMING/DONE/ERROR).
- B2  DONE | b59b7c30 | Visual agent handoff arc (HandoffCanvas sine-wave animation).
- B3  DONE | d2687aec | Live Constellation View (node-link diagram with SafeTick-driven states).
- B4  DONE | b59b7c30 | Smooth tab fade-in transitions.
- B5  DONE | b59b7c30 | Execute button success pulse on file move.

## PHASE C — Swarm & Code Intelligence (WHAT only)
Gate: v2.0 frozen. C3/C4 introduce code EXECUTION — each requires its own safety batch
(new threat surface) before merge; feature tests alone are not sufficient to merge.
- C1  DONE | 37f03ba2, 410cbdcf | Hierarchical swarm: Cortex parses a validated task breakdown,
      delegates to registered specialist workers, isolates worker failures, and synthesizes
      the surviving results. Foldy is a dry-run file preview, Scout is RAG search, and
      Syntax provides provider-backed text-only coding assistance with five intents. Accept:
      delegation start and each specialist completion are visible in Live Feed; worker count is
      bounded to eight; failure of one worker does not kill the run. Proof: HierarchicalSwarmTests,
      CodingAgentTests, and GUI delegation-routing tests; 236/236 unit tests green.
- C2  BACKLOG | Meta-prompting: architect produces a plan, builder implements it, as
      separate routed steps. Accept: plan artifact exists and is reviewable before any
      edit. Est 5-10h.
- C3  BACKLOG | AST-based surgical patches: model emits structured patch; applied via AST
      preserving comments and formatting. Accept: patch applies to a real file without
      destroying unrelated code; rejected cleanly on malformed patch. Est 15-25h.
- C4  BACKLOG | Self-healing loop: lint/run -> read stderr -> patch -> retry, with a hard
      iteration bound and a sandbox. Accept: loop terminates on bound; cannot escape
      sandbox; every iteration logged. Est 15-30h + safety batch.
- C5  DONE | 8665d86d | Persistent document RAG: ChromaDB ingestion, 500-character chunks with
      50-character overlap, default MiniLM embeddings, bounded retrieval, source-change
      replacement, recursive TXT/PDF/DOCX ingestion, and Scout Chat results. Proof:
      known-token retrieval and changed-file replacement covered by RAGTests; 138/138 green.

## PHASE D — Research-backed horizon (WHAT only; each is a new threat surface review)
- D1  BACKLOG | MCP support: connect external tool servers. Accept: one real MCP server
      usable from chat; server failure isolated. Est 8-15h.
- D2  BACKLOG | Screen-aware automation: screenshot -> vision analysis -> action.
      Accept: correct action on a controlled target; refuses ambiguous targets.
      Est 15-30h + safety batch.
- D3  DONE | 37f03ba2, 7d9d25c6, 518785a9 | Scheduled agents: an instance-local background
      scanner runs the real file categorization/move path at configurable 15-minute,
      30-minute, 1-hour, or 6-hour intervals. Preferences and last-run state survive restart
      in AppData. Generation-specific cancellation is checked between file operations; a
      timed-out stop returns failure; restart creates an isolated generation whose old worker cannot
      commit state or notifications into the replacement.
      Proof: ScheduledScannerTests cover execution, interval validation, persistence,
      cancellation, generation isolation, and isolated overlap; full unit suite green.
- D4  BACKLOG | Voice activation: wake word + speech-to-text command. Accept: hands-free
      command end-to-end; false-wake rate tolerable to owner. Est 10-20h.
- D5  BACKLOG | Phone remote control: authenticated API server. Accept: remote command
      executes only with valid auth; all remote actions sandboxed + logged.
      Est 10-20h + safety batch.

## Cross-cutting v2.1 backlog (not phases; do anytime post-freeze)
- Conversation memory DONE | 2b9e5031, 9641d1f1, HEAD | Supervisor retains bounded instance-local
  FILE_OP context; general Cortex chat retains at most 6 turns, 12,000 total characters, and
  4,000 characters per message. Clearing chat erases general-chat memory, invalidates pending
  or in-flight file previews, and rejects stale responses/UI continuations across all specialist
  paths.
- pytest migration of the suite
- Windows installer / packaging
- Broader test coverage beyond safety (router perf, GUI smoke)

## Rules of engagement
1. Work ONLY the batch or phase named in your prompt.
2. RED -> fix -> GREEN, pasting both outputs. Safety items also get mutation proof.
3. Security tests enter via execute_pending_plan() with a hostile plan, never convenience methods.
4. No invented items. Disputed items are marked DISPUTED with exact source lines.
5. Update statuses here in the closing commit; update HEAD on push; log structural changes.
6. Context death: commit proven work, write the handoff ledger INTO THIS FILE.
7. Environment: PowerShell (no &&, no rg, no tail), unittest not pytest, BOM files need
   utf-8-sig, protected files never modified, helper scripts outside the repo.

## Session start (the whole preamble)
Read ARCHITECTURE.md and PLAN.md. Work ONLY <BATCH-or-PHASE>. Follow Rules of engagement.
Update PLAN.md statuses and changelog in your closing commit.