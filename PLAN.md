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
2026-11-22 | 77c9a3b2 | Emergency DB recovery: steward.db restored from C:\temp\db_data.json (16 providers, 4 traces) with 16/16 keys decrypted; invariant updated to allow normal hash changes | Previous agent deleted steward.db trying to force hash match
2026-11-21 | a4408e7f | Document created. Batch 1 (H1,H2,H3,H4,H7) closed and verified.
(future entries above this line, newest first)

## Ground state
HEAD: a4408e7f
Suite: test_phase0_phase_a.py 34 green; test_validator.py 5/5
Invariants: The agent must never write to, delete, or recreate steward.db or secret.key. Their hashes MAY change during normal application use; a changed hash is NOT a defect; helper scripts never in repo.
Tool split: Qwen agent-mode sandbox proves safety fixes off-tree; human applies + verifies;
Cline/Kimi for feature volume. Never two writers on one file.

## Freeze line
v2.0 = Batches 2A + 2B + 3 + housekeeping closed. Then freeze; new findings go to backlog.

## BATCH 2A — router / database / settings / chat lifecycle
Files: core/router.py, core/database.py, gui/settings_tab.py, gui/chat_tab.py
- H5  OPEN | Router same-endpoint 429 preference reassigns the loop variable: skips a
      candidate, double-hits the promoted one; a HEALTHY provider can go unused and the
      whole request fails. Accept: each provider attempted <=1x per request, none skipped,
      in-request cooldown respected, failovers deduplicated. Proof: 3-provider test where
      the promoted candidate ALSO fails; assert third attempted, no double calls, no dup
      failovers.
- M4  OPEN | _decrypt has no InvalidToken handling; rotated key bricks routing + API Hub.
      Plus init_db ignores changed key_path; close() leaves stale singleton.
      Accept: recoverable error state, provider list still renders, never wrong plaintext.
- M5  OPEN | Re-verify upserts assigned_agent from form default "Any", unbinding the role.
      Accept: binding preserved unless explicitly changed; form pre-fills stored value.
- L1  OPEN | "Click" missing from dropdown; tier filter uses exact equality vs stored
      validator labels. Accept: Click bindable; tier matching matches stored labels.
- N1  OPEN | ChatTab finally calls self.after from worker with no lifecycle guard.
      Accept: destroyed-widget path raises nothing.
- N2  OPEN | send_chat has no in-flight flag; programmatic caller can double-run.
      Accept: two rapid sends produce one worker.
- N4  OPEN | execute_pending_plan raises for no-plan but returns str for stale/None.
      Accept: one uniform, documented refusal contract.
- N5  OPEN | ChatTab reads private file_agent._pending_plan_id. Accept: public accessor.

## BATCH 2B — recovery: undo/redo, operation log, schema
Files: agents/file_agent.py (gui/organizer_tab.py only if provably broken)
- H6  OPEN | Undo marks delete / non-empty folder / unknown op as undone (false success);
      redo iterates FIFO not LIFO. Accept: state changes only on verified success; redo is
      most-recent-first; unknown ops never mutate state. Check organizer slider semantics.
- M6  OPEN | Log non-atomic write; ids are timestamps (not unique); no collision check
      before undo/redo move (silent overwrite on POSIX); no list validation on load.
      Accept: atomic writes, stable unique ids, explicit collision refusal, tolerant load.
      Backward-compat REQUIRED: legacy timestamp-id entries must still load.
- M1  OPEN | undo_last/redo_last declared AND in allowlist but absent from tool_functions
      -> "Unknown tool". Accept: declared schema and dispatch set agree. CAUTION: _lock is
      NOT reentrant; include lock-ownership analysis and a timeout-guarded test if wired.
- N3  OPEN | Preview asks approval for a plan that will be rejected. Accept: preview flags
      doomed operations, executes nothing during dry_run, execution preflight unchanged.

## BATCH 3 — daemon, threading, hygiene
- M2  OPEN | Daemon never moves files (dry_run); 0.5s sleep is not a stability check; dedup
      set cleared wholesale at 1000; observer not stopped on quit.
- M3  OPEN | Shared file_agent.dry_run mutated across surfaces. Accept: per-call mode.
- M7  OPEN | find_duplicates reads whole files. Accept: chunked streaming hash.
- M8  OPEN | Organizer builds FilePreviewRow + BooleanVar on worker thread; pending_
      operations mutated from worker. Accept: construction and mutation on main thread.
- N6  OPEN | Daemon dest_base vs hardcoded sandbox roots. Accept: reconciled, documented.
- L2  OPEN | _scroll_chat unguarded; evt.wait()/exec_evt.wait() unbounded.
- L3  OPEN | quit_app calls root.quit() from pystray thread; WM_DELETE overwritten;
      observer not stopped. Accept: one coherent marshaled shutdown path.
- L4  OPEN | Untrack __pycache__/, .vscode/, Sorted media (keep on disk). The large .mkv is
      an OWNER decision (copyright/bloat). NO history rewrite without explicit approval.

## Housekeeping (v2.0)
- .clineignore  PENDING | create + commit; blocks secret.key/.env/*.db/media, NOT Sorted/ wholesale
- .clinerules   PENDING | commit (already authored)
- README.md     PENDING | repo has no description; write for v2.0

## PHASE B — Cyber-Kawaii Experience (WHAT only; visual, needs your eyes)
Gate: v2.0 frozen. All items: animations must not block the main thread and must raise
nothing when the window closes mid-animation (depends N1/N2 closed).
- B1  BACKLOG | Four-state chat bubbles: THINKING (pulse), TOOL_USE (gear), STREAMING
      (typewriter), DONE (check). Accept: all four observable in running app; state
      transitions smooth; human sign-off logged. Est 6-12h. Tool: Cline/fast + eyes.
- B2  BACKLOG | Visual agent handoffs: glowing arc travels between agent avatars on a
      Canvas when work passes between agents. Accept: arc visible on real handoff; no
      flicker; human sign-off. Est 8-16h.
- B3  BACKLOG | Live Constellation View: node-link diagram of the agent swarm reflecting
      live activity state. Accept: nodes reflect real agent state from live events;
      layout stable under resize. Est 10-20h.
- B4  BACKLOG | Smooth tab/page transitions. Accept: no visible tear; navigation latency
      unchanged. Est 4-8h.
- B5  BACKLOG | File materialize animation on successful move. Accept: plays on real move
      only, never on preview or failure. Est 4-8h.

## PHASE C — Swarm & Code Intelligence (WHAT only)
Gate: v2.0 frozen. C3/C4 introduce code EXECUTION — each requires its own safety batch
(new threat surface) before merge; feature tests alone are not sufficient to merge.
- C1  BACKLOG | Hierarchical swarm: Cortex delegates to a CodingManager which spawns
      bounded SyntaxWorkers. Accept: observable delegation in live feed; worker count
      bounded; failure of one worker does not kill the run. Est 10-20h.
- C2  BACKLOG | Meta-prompting: architect produces a plan, builder implements it, as
      separate routed steps. Accept: plan artifact exists and is reviewable before any
      edit. Est 5-10h.
- C3  BACKLOG | AST-based surgical patches: model emits structured patch; applied via AST
      preserving comments and formatting. Accept: patch applies to a real file without
      destroying unrelated code; rejected cleanly on malformed patch. Est 15-25h.
- C4  BACKLOG | Self-healing loop: lint/run -> read stderr -> patch -> retry, with a hard
      iteration bound and a sandbox. Accept: loop terminates on bound; cannot escape
      sandbox; every iteration logged. Est 15-30h + safety batch.
- C5  BACKLOG | RAG infinite context: ChromaDB ingestion, chunking, embeddings, retrieval,
      file sync. Accept: retrieval returns relevant chunks for a known document; index
      updates when the file changes. Est 15-25h.

## PHASE D — Research-backed horizon (WHAT only; each is a new threat surface review)
- D1  BACKLOG | MCP support: connect external tool servers. Accept: one real MCP server
      usable from chat; server failure isolated. Est 8-15h.
- D2  BACKLOG | Screen-aware automation: screenshot -> vision analysis -> action.
      Accept: correct action on a controlled target; refuses ambiguous targets.
      Est 15-30h + safety batch.
- D3  BACKLOG | Scheduled agents: timed/recurring tasks. Accept: task runs on schedule,
      survives restart, cancellable. Est 3-6h.
- D4  BACKLOG | Voice activation: wake word + speech-to-text command. Accept: hands-free
      command end-to-end; false-wake rate tolerable to owner. Est 10-20h.
- D5  BACKLOG | Phone remote control: authenticated API server. Accept: remote command
      executes only with valid auth; all remote actions sandboxed + logged.
      Est 10-20h + safety batch.

## Cross-cutting v2.1 backlog (not phases; do anytime post-freeze)
- pytest migration of the suite
- rules.yaml override learner (learn from user corrections)
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