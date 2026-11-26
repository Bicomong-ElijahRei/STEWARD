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
2026-11-26 | 5c337317 | D1-I1 pure MCP resource admission core: added a standard-library-only, transport-agnostic admission/read boundary with HTTPS and effective-origin pinning, explicit resource allowlisting, SHA-256 snapshot re-verification, byte bounds, deterministic redaction/truncation, typed refusals, single-admission revocation, and immutable external-only result containers; added 37 focused regressions and killed six targeted source mutants; no transport, SDK dependency, network/filesystem/process access, GUI integration, tool surface, local MCP resource, or MCP-caused local mutation was introduced; 507/507 tests green with the one known Windows symlink-privilege skip. | Establish the fail-closed, identity-pinned resource admission foundation before selecting the official MCP SDK and transport for D1-I2, while keeping remote content structurally outside routing and native-tool authority.
2026-11-26 | 9737c516 | D1-R MCP integration safety review: documented a 13-section threat/design review and RE-SCOPE decision for one explicitly admitted, identity-pinned, read-only remote MCP resource server usable from chat with server failure isolated; D1 remains BACKLOG, and stdio, invokable tools, local resources, and MCP-caused local mutation remain excluded; no code, dependency, configuration, README, or ROADMAP change was introduced; 470/470 tests green with the one known Windows symlink-privilege skip. | Decide the MCP authority and containment boundary before implementation while preserving proportionality and preventing remote server declarations from entering native dispatch authority.
2026-11-25 | 0acf370, 2e0fe28e | HYG-1 Patch Review background workers and retired-scope cleanup: moved proposal and apply off the Tk main thread into one bounded daemon-worker slot with epoch/closed-guarded result marshaling, single-flight apply, close/clear invalidation, and stale-result suppression; removed the orphaned retired desktop-control persona, routing, delegation, provider-choice, constellation, package-export, and skeleton surfaces; added truthful OUT_OF_SCOPE classification/refusal while preserving generic UNKNOWN behavior; left ROADMAP unchanged; 470/470 tests green with the one known Windows symlink-privilege skip. | Keep the Tk event loop responsive, prevent stale review state from publishing, and ensure removed-scope requests cannot be mistaken for an available persona or capability.
2026-11-25 | e7a462d2 | SCOPE-R1 documentation-only scope amendment: moved voice control, phone/remote control, and screen-aware automation/PC control from active Phase D into a historical Removed from scope record, marked each item deferred and removed from declared scope with rationale, added the orphaned PC-control persona cleanup backlog line, and left C4, MCP, scheduled agents, and running behavior unchanged. Roadmap completion changed from 22/27 checked (81.48%) to 22/24 checked (91.67%), and active Phase D changed from 1/5 checked (20%) to 1/2 checked (50%), solely because three unchecked scope items were removed; no work was completed and no running capability was added or removed. | Remove authority-granting surfaces from declared scope where containment and proportionality cannot be proven, preserving history without changing runtime capability.
2026-11-25 | 3afe56aa | C4-ISO Windows isolation research: documented exact read-only host findings, eight isolation candidates, an all-20-criterion capability matrix, conditional hash-bound artifact-transfer/provenance design, dependency decision, future proof plan, and fail-closed refusal policy; selected no baseline and DEFERRED C4-I2. | Convert the binding C4-R isolation gate into an evidence-backed host/candidate decision without introducing execution or silently weakening the review criteria; C4 itself remains BACKLOG.
2026-11-25 | 4c794ec2 | C4-I1 pure iteration controller: added a bounded, injected-interface-only healing controller with a structural hard iteration bound, write-ahead intent/outcome/terminal journal ordering, deterministic bounded+redacted observations, truthful termination states, controller-owned timeouts, and 25 focused tests proving no execution and no auto-apply. | Establish the coordination layer C4 needs while keeping every execution surface out of the tree until the C4-R gate is satisfied; C4 itself remains BACKLOG.
2026-11-25 | 8f3cb0da | C4-R execution safety review: documented an 11-section threat/design review deciding a fixed no-shell command allowlist, OS-level Windows isolation, a separate single-use execution grant in addition to C3's byte-only exact-diff approval, controller-owned bounds, bounded/redacted observations, truthful recovery, and future C4-I2 acceptance criteria. | Decide the safety gate before any C4 executor is written; C4 remains BACKLOG and real execution is deferred until OS-level isolation is proven.
2026-11-25 | b1878548 | C3-F1 provider tier label correction: corrected Patch Review's caller tier literal from "Tier1" to "Tier 1" and added real-matcher structural and focused provider-selection regressions. | Make Patch Review proposals eligible for existing Tier 1 validator providers without changing router semantics, validator labels, or GUI behavior.
2026-11-25 | 6c9017ed, 0da71eda | C3-I3 user-integrated exact-diff patch review: added immutable artifact persistence, epoch/plan/workspace/hash/diff-bound single-use approval, guarded real-file apply, Patch Review GUI, lifecycle invalidation, and 37 focused acceptance regressions. | Complete the §13 one-file review/approval acceptance path without granting target execution or weakening the organizer sandbox.
2026-11-24 | 8546e051 | C3-I1 pure AST patch staging foundation: added strict one-file artifact validation, definition AST anchors, byte-preserving replace/insert staging, exact outside-range proofs and deterministic diffs, 36 focused tests, and five mutation proofs; no filesystem, execution, approval, or persistence surface was added. | Establish a reviewable deterministic staging core while keeping C3 mutation and C4 execution in BACKLOG.
2026-11-24 | 279023e7 | C3-I2 admitted content replacement: added one-file workspace/target admission, exact engine-proof and source revalidation, same-directory atomic replacement, durable intent/completion/failure journal states, exact pre/post backups, hash-guarded undo/redo, and 39 focused regressions. | Add a safe internal mutation/recovery surface for one explicitly selected Python file without execution, linting, target tests, or UI integration.
2026-11-24 | 1c59da0f | C3-I2 documentation closure: record the admitted replacement/recovery boundary, safety contract, exact 391-test baseline, implementation commit 279023e7, and remaining approval/UI limitations. | Align PLAN, ARCHITECTURE, and README without changing ROADMAP or claiming user-integrated C3 completion.
2026-11-24 | fbfb42fc | C3-R AST patch safety review: documented a 13-section threat/design review and RE-SCOPE decision; C3 and C4 remain BACKLOG, with eventual C3 requiring a separate explicitly selected code-workspace mutation root. | Establish bounded exact-approval and content-recovery criteria without introducing a code mutation surface or weakening Incoming/Sorted.
2026-11-24 | 883347bf | Phase C7 static dependency-graph context: added identifier-only import/call edge derivation from the existing bounded C6 admission reads, root-scoped graph persistence/traversal, bounded semantic retrieval expansion, changed/deleted-file edge reconciliation, and header-inclusive provider context accounting with 316/316 unit tests green. | Expand repository context across statically visible dependencies without executing code, reading denied/external paths, or changing provider payload limits.
2026-11-24 | 8e8d4f34 | C6 code-index review hardening: deny selected roots whose own basename is in `DENIED_DIRECTORIES` before traversal while retaining filename secret rules. | Close the C6 review finding without weakening existing secret-path exclusions.
2026-11-24 | a96eb888 | Phase C6 code context: added a bounded, read-only persistent CODE collection with explicit-root traversal, denylisting, symbol-aware chunks, hash-based incremental replacement, scoped retrieval, GUI lifecycle controls, bounded Syntax prompt context, and 281/281 unit tests green. | Ground Syntax in repository code without granting code execution or mutation capability.
2026-11-24 | 1c66ecb9 | Phase C2 meta-prompting: added schema-validated Cortex plan artifacts, explicit ID-bound approval, and a separate text-only Syntax request; architect and builder remain text-only and automated application remains C3. | Keep plan creation reviewable without implying file mutation capability.
2026-11-23 | eaee322b | FS-S5 closure: journal serialization is implemented and pushed; closure state, implemented SHAs, freeze line, and push metadata are reconciled. | Keep the tracked plan aligned with the verified Git closure baseline and prevent stale local/not-pushed claims.
2026-11-23 | 935a6236 | FS-S5 DONE: implemented persistent sidecar OS locking, bounded timeout, crash release, stale-transition protection, write-ahead/atomic journal guarantees, cross-process regressions, and 266/266 discovery tests green. | Prevent lost journal updates and conflicting undo/redo transitions when separate STEWARD processes share the AppData operation log.
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
Implementation baseline: D1-I1 pure MCP resource admission core commit 5c337317; HYG-1 Patch Review worker and retired-scope cleanup commits 0acf370, 2e0fe28e
Acceptance baseline: D1-I1 focused mutation-tested resource admission suite; 507/507 discovery tests green
Review baseline: D1-R MCP integration safety review commit 9737c516
Execution review baseline: C4-R execution safety review commit 8f3cb0da
Isolation research baseline: C4-ISO Windows isolation research and decision commit 3afe56aa
Documentation baseline: C4 documentation reconciliation commit 7b427437
Suite: 507/507 unit tests green with one expected Windows symlink-privilege skip; validator 5/5; compileall and diff checks green
Roadmap denominator (scope removal only): whole ROADMAP 22/27 checked (81.48%) before -> 22/24 checked (91.67%) after; active Phase D 1/5 checked (20%) before -> 1/2 checked (50%) after. The completion percentage increased only because scope was removed, not because work was completed.
Scope declaration baseline: SCOPE-R1 documentation-only amendment commit e7a462d2; HYG-1 commit 2e0fe28e subsequently removed the orphaned active persona/routing without adding capability; D1-R commit 9737c516 re-scoped the still-BACKLOG D1 MCP item to one read-only remote resource server without adding capability.
Push state at verification: `origin/main` remains at 05abaac0. D1-R review commit `9737c516` is a local ancestor of this closing commit and awaits human push; no push is claimed. Previously recorded implementation/documentation SHAs remain pushed ancestors of `origin/main`.
Bare-subject deviation ledger: `8e8d4f34`, `9dbf774d`, and `96dcfe14` are confirmed
pushed ancestors with bare commit subjects and no structured Problem/Design/Fix/Impact/
Tests/Gates body. They are not rewritten because they are already public history; C7 commit
`883347bf` and its documentation closure use the required structured body.
Persistent state: `%APPDATA%\STEWARD`; legacy repository-root files are copied, never moved or overwritten.
Invariants: The agent must never write to, delete, or recreate steward.db or secret.key. Their hashes MAY change during normal application use; a changed hash is NOT a defect; helper scripts never in repo.
Tool split: Qwen agent-mode sandbox proves safety fixes off-tree; human applies + verifies; Cline/Kimi/Antigravity for volume. Never two writers on one file.

## Implemented
- D1-I1 Pure MCP resource admission core — DONE | 5c337317 |
  standard-library-only, transport-agnostic admission/read boundary for one explicitly selected,
  identity-pinned remote resource server. HTTPS identities and effective origins are canonicalized
  and pinned; private/reserved literal hosts, local suffixes, credentials, fragments, queries, and
  tools-capable servers fail closed. Every allowed resource must be explicitly listed and advertised;
  a SHA-256 snapshot fingerprint is re-verified before each read. Content is byte-bounded,
  deterministically redacted/truncated, and returned only in an immutable external-only container with
  routing and native-tool eligibility permanently false. Proof: 37 focused regressions, 507/507
  discovery tests, validator 5/5, compileall/diff checks green, and six targeted source mutants killed.
  Limitation: no transport, official SDK dependency, chat/GUI integration, or runtime MCP capability
  is implemented; overall D1 remains BACKLOG pending D1-I2.
- v3.0 Safe-Intelligence Foundations — DONE | 61390dca, 518785a9, 9641d1f1, 410cbdcf, 7907ebb1, e1a37c30, 935a6236, eaee322b
  explicit shared-credential rotation; generation-safe scheduled scans; bounded Cortex
  general-chat memory with stale-response rejection; provider-backed text-only Syntax across
  generation/debugging/refactoring/review/explanation; generation-owned file previews with
  epoch-guarded approval/execution/provider/specialist continuations; no-overwrite
  filesystem publication with durable write-ahead operation history; truthful no-op/failed/
  uncertain journal outcomes; and whole-plan file/directory conflict detection.
  Proof: 281/281 unit tests green, including cross-process journal serialization and bounded source-integrity encoding coverage.
- Persistent state relocation — DONE | b99c9a38 | Database, Fernet key, and operation log
  use `%APPDATA%\STEWARD`; legacy root files are copied without overwrite and the legacy
  sources remain intact. Proof: AppDataMigrationTests.
- Phase C2 Meta-prompting — DONE | 1c66ecb9 | Cortex creates a strict, bounded,
  schema-validated immutable JSON plan artifact under the app-owned plans directory.
  The GUI exposes an explicit Plan first mode only for validated CODING routing;
  a single-use approval bound to the plan UUID starts a separate text-only Syntax
  request. Targets are informational and never reach FileAgent; no file changes are
  applied by either step. Proof: BlueprintValidationTests, PlanPersistenceTests,
  PlanReviewGateTests, PlanGuiLifecycleTests; 306/306 unit tests green.
- Phase C7 Static dependency-graph context — DONE | 883347bf | Python import/call
  edges are statically derived during the existing bounded C6 admission read, persisted as
  identifier-only scalar metadata, traversed with deterministic root-scoped bounds, and used
  to expand semantic context across files. Resolution never imports or executes source and
  resolves only against admitted root inventory; external/unresolved/denied module strings
  cause no reads. Provider limits remain five snippets, 2,000 characters per snippet, and
  8,000 total characters including headers. Proof: DependencyGraphCodeIndexTests; 316/316
  unit tests green. Limitation: name-based static approximation does not resolve dynamic
  imports, aliases, ambiguous symbols, or runtime behavior.
- Phase C6 Codebase-scale semantic context — DONE | a96eb888, 8e8d4f34 | Separate
  persistent `steward_code` collection provides explicit-root, bounded, read-only symbol
  retrieval for Syntax, with denylisting, containment, incremental replacement, GUI lifecycle
  controls, and provider disclosure. Review hardening refuses a selected root whose own
  basename is in `DENIED_DIRECTORIES` before traversal while retaining filename secret rules.
  Proof: CodeIndexAgentTests, SyntaxCodeContextTests, and ChatCodeIndexLifecycleTests;
  307/307 unit tests green.
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
v2.1 closed: 4a, 4b, and 4c complete. v2.2 Visuals & RAG complete through C5. v2.3 Learning & Rules closed at f1d98141. v2.4 Hierarchical Swarm & Scheduling closed at 7d9d25c6. v3.0 safe-intelligence foundations current through the FS-S5 journal-serialization closure eaee322b. New findings go to the backlog.

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
- FS-S5  DONE | cc4800de, 935a6236, eaee322b | The operation journal uses process-local `threading.RLock`
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
      Proof: Windows subprocess regressions pass; 267/267 discovery tests, 5/5 validator checks,
      compileall, and diff checks are green. Implementation commit: `935a6236` (pushed; confirmed
      ancestor of `origin/main`). Closure commit: `eaee322b` (pushed; confirmed ancestor of
      `origin/main`).

- FS-S5-CLOSURE DONE | fc3cc0ee | Confirmed the reported arrow corruption in 11 user-facing
      string literals in `agents/file_agent.py`; restored only the intended `→` characters and added a
      bounded `SourceIntegrityTests` regression over tracked Python sources (venv excluded, utf-8-sig).
      Proof: focused regression RED with 22 signature findings, then GREEN; 267/267 unit tests,
      5/5 validator checks, compileall, and diff checks green. Encoding repair commit: `fc3cc0ee`
      (local; not pushed).

### FS-S5 closure handoff ledger
- Verified baseline: `eaee322b`; origin/main was synced at verification. The pre-existing
  FS-S5 implementation `935a6236` and closure `eaee322b` are confirmed pushed ancestors of
  `origin/main`; the stale `local; not pushed` claim was removed.
- Encoding finding: confirmed, not disputed. Exact affected literals were `agents/file_agent.py`
  lines 683, 705, 790, 810, 1304, 1306, 1310, 1314, 1342, 1344, and 1499 before repair.
- Repair: `fc3cc0ee` restores `→` in those 11 literals only and adds one bounded tracked-Python
  regression. BOMs and line endings were not altered.
- Push handoff: `fc3cc0ee` and this plan-reconciliation commit are local; a human must push them.
  Do not claim they are pushed until `origin/main` confirms them.

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
- C2  DONE | 1c66ecb9 | Meta-prompting: Cortex creates a schema-validated immutable
      plan artifact; after explicit ID-bound review approval, a separate text-only Syntax
      request elaborates it. Accept: plan artifact exists and is reviewable before any
      builder request; no file changes are applied. Proof: 306/306 unit tests green.
- C3  IN-PROGRESS | AST-based surgical patches: C3-I1 adds the pure one-file staging
      foundation (commit 8546e051), C3-I2 adds admitted content replacement/recovery for
      one explicitly selected Python file (commit 279023e7), and C3-I3 integrates immutable
      exact-diff review, epoch/workspace/hash-bound single-use approval, GUI workspace/target
      selection, and the final guarded real-file apply path. C3-R RE-SCOPE requires a new
      explicitly user-selected code-workspace mutation root disjoint from Incoming/Sorted,
      formatting-preserving stdlib AST/token splicing, bounded files/edits, journaled
      content undo/redo, and no execution in v1. Review: docs/ast_patch_review.md. Accept:
      patch applies to a real file without destroying unrelated code; rejected cleanly on
      malformed patch. C3-I3 completes the one-file review/approval slice; multi-file and
      self-healing C3/C4 work remains future scope.
- C4  BACKLOG | Self-healing loop: lint/run -> read stderr -> patch -> retry, with a hard
      iteration bound and a sandbox. Accept: loop terminates on bound; cannot escape
      sandbox; every iteration logged. C4-R (execution safety review, commit 8f3cb0da) is
      DONE and decided PROCEED for the pure C4-I1 controller only, with real execution
      DEFERRED until an OS-level Windows isolation boundary is selected and proven;
      C4-I1 (pure iteration controller, commit 4c794ec2) is DONE and adds no executor;
      C4-ISO (Windows isolation research, commit 3afe56aa) is DONE and DEFERRED C4-I2
      after finding no supported, proven baseline on this Windows 11 Home host. The
      executor, sandbox, artifact transfer, and execution grant remain BACKLOG. Est
      15-30h + safety batch on a qualified host.
- C5  DONE | 8665d86d | Persistent document RAG: ChromaDB ingestion, 500-character chunks with
      50-character overlap, default MiniLM embeddings, bounded retrieval, source-change
      replacement, recursive TXT/PDF/DOCX ingestion, and Scout Chat results. Proof:
      known-token retrieval and changed-file replacement covered by RAGTests; 138/138 green.
- C6  DONE | a96eb888 | Codebase-scale semantic context: a separate persistent `steward_code`
      Chroma collection indexes an explicitly selected project root without executing or
      modifying source. Python AST symbols, bounded overlapping fallback chunks,
      denylisted/secret paths, symlink/junction containment, per-file byte and file-count
      limits, content-hash replacement/deletion, root-scoped retrieval, status, and clear are
      implemented. GUI indexing runs in a cancellable background worker with main-thread
      result marshaling and generation guards. Syntax receives at most five path/line-aware
      snippets (8,000 total characters) in its existing text-only provider prompt; no tool,
      file-write, or code-execution capability is added. Accept: a known symbol retrieves
      with path/lines, unchanged files are idempotent, changed/deleted files replace prior
      chunks, denied/escaping paths are never opened, clear-chat rejects stale index UI, and
      provider/tool safety remains intact. Review hardening also refuses a selected root
      whose own basename is in `DENIED_DIRECTORIES` before traversal; filename secret
      rules remain active. Proof: CodeIndexAgentTests, SyntaxCodeContextTests, and
      ChatCodeIndexLifecycleTests; 307/307 unit tests green.
- C7  DONE | 883347bf | Dependency-graph modeling: an explicit static import/call graph is
      derived without executing code, persisted as bounded identifier-only root-scoped
      metadata, traversed with deterministic depth/node/edge limits, and used to expand
      semantic repository context. Changed/deleted files reconcile edges idempotently.
      Accept: external/unresolved/denied module strings cause no reads, relevant cross-file
      dependencies are found without root leakage, and provider snippet/character limits are
      unchanged. Proof: DependencyGraphCodeIndexTests; 316/316 unit tests green.

## BATCH C3-I1 — pure AST patch staging foundation (CLOSED)
Files: agents/patch_engine.py, test_patch_engine.py, ARCHITECTURE.md, README.md, PLAN.md
- C3-I1  DONE | 8546e051 | Added a pure, I/O-free staging engine for exactly one
  already-admitted Python file. Strict duplicate-free JSON and exact-key schema validation
  bind the raw artifact and decoded object; definition anchors use node kind, canonical
  `Module...` qualified name, occurrence, and checked character offsets. V1 operations are
  `replace_node`, `insert_before`, and `insert_after`; `delete_node` is unsupported. Limits
  are 20 edits, 16 KiB per edit (replacement plus anchor metadata), 256 KiB raw artifact,
  and 1 MiB each for input and output. The engine preserves UTF-8 BOM and LF/CRLF mode,
  refuses undecodable/mixed encoding, parses original and output without execution, and
  returns deterministic unified-diff and exact outside-edited-range byte proofs.
  Accept: malformed artifacts, paths, anchors, overlaps, bounds, encodings, and invalid
  output fail closed; deterministic identical inputs produce identical bytes/diff/proof;
  unrelated bytes are exactly equal; the module performs no filesystem, subprocess,
  target-import, target-execution, lint, or test operation. Proof: 36 focused regressions,
  352/352 discovery tests, validator 5/5, compileall and diff checks green, plus five
  targeted mutation proofs (duplicate keys, edit bound, overlap, mixed newline, and
  non-execution) each RED under a weakened guard and GREEN after restoration. Limitation:
  no workspace admission, path resolution, mutation, approval, persistence, journal, undo,
  or user-facing integration is implemented; C3 and C4 remain BACKLOG.

## BATCH C3-I2 — admitted content replacement and recovery (IMPLEMENTED)
Files: agent/content_replace.py, agents/patch_applier.py, test_patch_applier.py, ARCHITECTURE.md, README.md, PLAN.md
- C3-I2  DONE | 279023e7 | Added an internal mutation surface for exactly one
  explicitly selected existing `.py` file under a separately admitted workspace. Admission
  rejects drive/home/app-data roots, organizer-root overlap, traversal/absolute paths,
  non-Python targets, secret/cache/control paths, symlink/junction/reparse components,
  non-regular files, and sources over 1 MiB. Backup storage must be disjoint from the
  workspace, Incoming, and Sorted roots.
  The C3-I1 engine remains pure and is called only after workspace fingerprint, source
  hash/identity, and exact outside-edit byte proofs are verified. A same-directory unique
  staging file is hash-checked and replaced with `os.replace`; target and staged paths must
  be regular non-link files and the target must still match the recorded pre-image hash.
  The target is never executed, imported, linted, or tested.
  Durable journal state records intent before backup/replacement and completion afterward.
  Intent-persistence failure causes zero target writes; failed pre-replacement work is
  marked failed; a failure after the replacement boundary is classified by observed target
  hash as committed, failed, or uncertain. Exact pre/post bytes are stored in an app-owned
  backup outside the workspace with a metadata-only manifest; partial backups are removed.
  Undo/redo is journal-locked, hash-guarded, blocked by uncertain content edits, restores
  exact backup bytes, and preserves the existing FIFO redo order.
  Accept: source revalidation precedes replacement; malformed/tampered proofs and changed
  targets produce zero writes; intent precedes mutation and completion follows it; exact
  backups and safe external-edit refusal are covered; separate processes cannot both
  claim one undo. Proof: 39 focused regressions, 391/391 discovery tests, validator 5/5,
  compileall and diff checks green, plus targeted mutation proofs for source revalidation,
  outside-byte proof, pre-replacement hash guard, atomic replacement, uncertain-state
  blocking, and recovery hash guard, each RED under a weakened guard and GREEN after
  restoration. Limitation: no immutable exact-diff single-use approval, UI workspace/target
  selection, or user-facing workflow is integrated in C3-I2; C3 remains IN-PROGRESS.

## BATCH C3-I2-DOCS — C3-I2 documentation closure (IMPLEMENTED)
Files: PLAN.md, ARCHITECTURE.md, README.md
- C3-I2-DOCS  DONE | 1c59da0f | Record C3-I2's admitted replacement/recovery boundary,
  safety rules, journal/backup states, exact 391-test baseline, implementation commit
  `279023e7`, and remaining user-integration limitations. Accept: architecture, README,
  and plan agree; no immutable approval/UI or user-integrated C3 completion is claimed;
  ROADMAP remains unchanged.

## BATCH C3-I3 — user-integrated exact-diff review and approval (IMPLEMENTED)
Files: agents/patch_review.py, gui/patch_review_dialog.py, gui/chat_tab.py, gui/main_window.py, agents/agent_config.py, test_patch_review.py, README.md, ARCHITECTURE.md, ROADMAP.md, PLAN.md
- C3-I3  DONE | 6c9017ed, 0da71eda | Added a shared PatchReviewManager and Patch Review GUI
      for the latest reviewed C2 plan. The user explicitly selects a separate code workspace and one
      admitted Python target; a text-only Syntax proposal is staged through C3-I1 and persisted as an
      immutable exact-diff artifact. A distinct single-use approval binds conversation epoch,
      reviewed plan ID, canonical workspace fingerprint, relative target, source/output hashes,
      exact-diff SHA-256, and artifact SHA-256. Changed source/workspace/artifact/diff/plan/epoch,
      stale/replayed approval, hostile provider paths/diffs, malformed responses, and journal-lock
      contention fail closed. Failed apply clears pending proposal/approval state; clearing chat
      invalidates the state and closes the dialog; an unapproved preview may be replaced but an
      approved proposal cannot be stranded. Apply and recovery use the shared operation journal lock
      and C3-I2 hash-guarded, workspace-scoped backup/undo/redo path. The target is never executed,
      imported, linted, or tested.
      Accept: all §13 criteria applicable to the bounded one-file v1 are covered, including a
      real-file apply, unrelated-byte preservation, exact artifact/diff identity, workspace
      isolation, hostile path/diff refusal, mutation resistance, epoch cancellation/invalidation,
      single-use approval, cross-process contention, truthful uncertain recovery, and no target
      execution. The multi-file partial-apply branch is inapplicable because C3-I3 admits exactly
      one file. Proof: 37 focused regressions and 428/428 discovery tests green; validator 5/5,
      compileall, BOM, and diff checks green. Six targeted C3-I3 mutation proofs each produced RED
      with the relevant guard weakened and GREEN after restoration, supplementing the inherited
      C3-I1/C3-I2 mutation proofs.

## BATCH C3-F1 — provider tier label correction (IMPLEMENTED)
Files: agents/patch_review.py, test_provider_tier_labels.py, ARCHITECTURE.md, README.md, PLAN.md
- C3-F1  DONE | b1878548 | Corrected the Patch Review proposal caller's required tier from
      `Tier1` to the existing validator-compatible `Tier 1`. The real matcher rejected `Tier1`
      against `Tier 1: Genius`, so the fix changes only the caller and does not alter router
      semantics, validator labels, or GUI behavior. Added an AST structural guard over tracked
      Python sources and a focused real-router regression with a realistic eligible provider row.
      Proof: focused RED produced two failures, including the exact `agents/patch_review.py:207`
      finding; focused GREEN passed 2/2; 430/430 discovery tests passed with the one known Windows
      symlink-privilege skip; validator 5/5; compileall and diff checks passed.

## BATCH HYG-1 — Patch Review background workers and retired scope cleanup (IMPLEMENTED)
Files: agents/agent_config.py, agents/supervisor.py, agents/pc_agent.py, agents/__init__.py, core/theme.py, gui/chat_tab.py, gui/constellation_view.py, gui/patch_review_dialog.py, gui/settings_tab.py, test_hygiene_scope.py, test_patch_review_workers.py, test_phase0_phase_a.py, README.md, ARCHITECTURE.md, PLAN.md
- HYG-1  DONE | 0acf370, 2e0fe28e | Patch Review proposal and apply now run in one bounded daemon-worker slot; the Tk thread snapshots request inputs, workers call only the existing manager, and every result returns through ChatTab's epoch-aware scheduler. A separate apply-in-flight guard refuses a second apply, captured-input controls are disabled during work and restored on completion/refusal/failure, and close/clear invalidate local and manager state while stale results publish nothing. The same batch removed the orphaned retired desktop-control persona and all active routing/UI/provider-choice/delegation/package/skeleton references, replacing residual legacy classification with a truthful OUT_OF_SCOPE refusal while arbitrary invalid classifications remain UNKNOWN.
      Accept: provider work does not execute on the Tk thread; stale/closed proposal and apply results cannot update preview, approval, result, controls, or Live Feed; close/clear use existing cancel/invalidation paths; one apply runs at a time; exact-diff approval/refusal/journal/admission/hash/recovery semantics are unchanged; no retired persona or exact legacy category token remains in active source; out-of-scope chat performs no delegation and states that no action was taken; ROADMAP remains unchanged.
      Proof: focused RED produced 9/9 worker-lifecycle failures and 5/6 removed-scope failures before implementation. Final focused suites passed 46/46 and 38/38; 470/470 discovery tests passed with the one known Windows symlink-privilege skip; validator 5/5; compileall and diff checks green. Three targeted mutation proofs each produced RED with the relevant stale-result, apply-single-flight, or legacy-remap guard weakened and GREEN after byte-exact restoration.

## BATCH C3-R — AST patch safety review (CLOSED)
Files: docs/ast_patch_review.md, PLAN.md
Review document: docs/ast_patch_review.md
- C3-R  DONE | fbfb42fc | Completed a documentation-only, 13-section AST patch safety/threat
      review covering scope, threats, three mutation-boundary options, patch schema,
      formatting/comment preservation, approval, journal/recovery, blast-radius caps,
      failure/rollback, UI impact, future RED->GREEN proof, residual risks, and eventual
      acceptance criteria. Decision: RE-SCOPE to a new explicit code-workspace mutation root
      parallel to and disjoint from Incoming/Sorted; C3 and C4 remain BACKLOG. No code, tests,
      dependencies, UI, or behavior changes were introduced. Proof: 316/316 existing unit tests
      green; validator 5/5; compileall and diff checks green.

## BATCH C4-R — execution safety review (DONE)
Files: docs/self_healing_review.md, PLAN.md
Review document: docs/self_healing_review.md
- C4-R  DONE | 8f3cb0da | Completed a documentation-only, 11-section execution
      safety/threat review for C4, the project's first code-execution surface.
      Decision: PROCEED with the pure C4-I1 controller and DEFER all real execution
      until an OS-level Windows isolation boundary (Sandbox/VM/container, or Job
      Object plus restricted token/ACL/firewall controls proven for the whole child
      tree) is selected and validated. The review fixes a command policy (fixed
      application-owned interpreter/linter profiles, no shell, no string
      interpolation of model output, no user-supplied arbitrary commands), an
      isolation decision (scrubbed environment, default-deny network, disposable
      copy, OS-enforced resource limits, and a plain statement of what
      Python-level subprocess controls cannot enforce on Windows), and an approval
      decision: C3's approval authorizes BYTES only, C4 must NEVER auto-apply a
      patch, and every iteration's patch must pass the existing single-use exact-diff
      C3 gate while execution itself needs a separate explicit bounded grant.
      It also specifies controller-owned iteration bounds, bounded/redacted
      observations, write-ahead journal/recovery truthfulness, failure and abort
      semantics, residual risks, and 20 acceptance criteria for the future C4-I2
      executor batch. No executor, subprocess, sandbox, GUI wiring, provider call,
      patch-application path, or runtime behavior was introduced. C4 itself REMAINS
      BACKLOG. Proof: 430/430 existing unit tests green; validator 5/5; compileall
      and diff checks green; strict UTF-8 decode and required section-order check
      on the review document.

## BATCH C4-I1 — pure iteration controller (DONE)
Files: agents/healing_controller.py, test_healing_controller.py, ARCHITECTURE.md, README.md, PLAN.md
- C4-I1  DONE | 4c794ec2 | Added a pure, bounded iteration controller over INJECTED
      interfaces. The module performs NO execution (no process, shell, or dynamic-code
      surface) and cannot apply patches. It structurally checks and increments its
      iteration counter before every iteration, so the executor cannot extend the
      bound; writes a durable intent record before the executor call and an outcome
      record after it (plus one terminal record), reusing the write-ahead ordering of
      FileAgent._begin_mutation/_complete_mutation/_save_operation_log_locked; bounds
      and redacts observations deterministically with truncation and redaction
      reporting; and terminates deterministically on bound reached, success,
      unrecoverable error, executor exception, invalid result, cancellation, repeated
      identical failure, iteration/total timeout, and journal failure. Cancellation
      is checked between iterations at a safe boundary. A journal-write failure before
      an iteration prevents that iteration from running; a failure after execution
      yields the truthful `uncertain` state. The controller exposes no patch-application
      path and may only request that a proposal enter the existing C3 single-use
      exact-diff approval gate. No executor, sandbox, GUI wiring, provider call, or
      filesystem mutation exists in the module; C4 REMAINS BACKLOG.
      Proof: focused RED was ModuleNotFoundError: No module named
      'agents.healing_controller'; focused GREEN passed 25/25 focused tests and
      455/455 discovery tests with the one known Windows symlink-privilege skip;
      validator 5/5; compileall and diff checks green. Mutation proof: weakening the
      structural bound check from `iteration >= self.max_iterations` to
      `iteration > self.max_iterations` produced RED
      (`AssertionError: 'repeated_failure' != 'bound_reached'`, a fourth executor
      call); restoring the check returned the focused test and the full controller
      suite to GREEN.

## BATCH C4-ISO — Windows isolation research and decision (DONE)
Files: docs/windows_isolation_research.md, ARCHITECTURE.md, PLAN.md
- C4-ISO  DONE | 3afe56aa | Completed a research-only host qualification and Windows
      isolation decision for the future C4-I2 executor. The document records the exact
      read-only probe allowlist and empirical findings; compares Windows Sandbox,
      Hyper-V VM, WSL2/Linux guest, Windows containers, Job Object + restricted token +
      ACL + firewall, AppContainer, third-party sandbox, and Python-only/no-boundary
      candidates; maps all eight against all 20 C4-R acceptance criteria; defines a
      conditional hash-bound data-only source/artifact transfer with protected provenance;
      approves no new Python or third-party dependency; specifies the criterion-by-criterion
      future test strategy; and requires fail-closed refusal with no silent downgrade.
      Decision: DEFER C4-I2 and keep C4 BACKLOG. Windows Sandbox is unsupported on the
      observed Home edition; the Hyper-V role is outside the observed client edition's
      supported editions; optional-feature state remains unknown because authoritative
      queries require elevation; no candidate boundary was constructed or proven. No
      executor, sandbox, transfer implementation, execution grant, test, dependency, GUI
      wiring, provider call, patch-application path, or runtime behavior was introduced.
      Proof: read-only systeminfo, whoami /priv, DISM/Get-WindowsOptionalFeature refusal,
      and netsh advfirewall probes; structural checks for 11 ordered sections, 32 matrix
      candidate rows, and all 20 proof-plan criteria; 455/455 unit tests green with the
      one known Windows symlink-privilege skip; validator 5/5; compileall and diff checks
      green. C4-I2 remains BACKLOG pending a supported host or explicitly approved
      candidate baseline in a new focused design/proof batch.

## BATCH D1-I1 — pure MCP resource admission core (DONE)
Files: agents/mcp_resource_core.py, test_mcp_resource_core.py
- D1-I1  DONE | 5c337317 | Added a pure, standard-library-only MCP resource
  admission/read core over an injected transport protocol. It admits exactly one
  explicitly selected remote server at a time, canonicalizes and pins the HTTPS
  identity plus effective origin (including non-default ports), requires an exact
  server-reported identity, refuses any advertised tools capability, and admits only
  an explicit unique resource allowlist whose canonical URIs are advertised by the
  server. The SHA-256 fingerprint covers normalized identity, reported server
  identity, normalized capabilities, and order-independent canonical advertised
  resources; it is re-verified before every read. Content is bounded per resource,
  per admission total, and by URI length, then deterministically redacted and
  truncated before construction of an immutable external-only result container.
  Revocation or successful re-admission invalidates the prior admission and cached
  content. Transport exceptions are normalized to a bounded typed refusal.
  Accept: non-HTTPS, non-remote literal hosts, local suffixes, userinfo, fragments,
  malformed percent escapes, all query-bearing URLs, non-default/origin mismatches,
  tools-capable servers, unknown/changed resources, duplicate/count/type violations,
  changed identities/capabilities/resources, oversized content, and transport failures
  fail closed; public IDNA and IPv6 identities canonicalize correctly; redaction and
  truncation are deterministic; result containers cannot be publicly forged or
  mutated and always carry `routing_eligible=False` and
  `native_tool_eligible=False`. The module imports no MCP SDK and performs no
  network, filesystem, subprocess, dynamic-code, JSON-RPC, GUI, tool, or local
  mutation operation.
  Decisions: v1 refuses literal loopback, private, reserved, link-local,
  multicast, and unspecified IPv4/IPv6 addresses plus localhost/local-domain
  suffixes; it conservatively refuses every query-bearing URL because an arbitrary
  query value cannot be proven credential-free. A server advertising both resources
  and tools is rejected wholesale rather than partially admitted, so D1-I1 is
  intentionally incompatible with resource-and-tools servers even though the core
  never invokes tools. D1-I1 adds no dependency. The official MCP SDK remains the
  selected D1 transport choice, but exact-version and transitive-dependency review
  is a mandatory D1-I2 prerequisite before adding it.
  Proof: 37/37 focused tests; 507/507 discovery tests green with the one known
  Windows symlink-privilege skip; validator 5/5; compileall and diff checks green.
  Six targeted source mutants covering tools refusal, fingerprint verification,
  allowlisting, bounds/redaction, transport normalization, and structural isolation
  each produced an assertion RED and were killed; the original source remained
  GREEN. Limitation: no real MCP transport, SDK, chat surface, or end-to-end server
  exists, so D1 remains BACKLOG.

## BATCH D1-R — MCP integration safety review (DONE)
Files: docs/mcp_integration_review.md, PLAN.md
Review document: docs/mcp_integration_review.md
- D1-R  DONE | 9737c516 | Completed a documentation-only, 13-section MCP integration
      safety/threat review covering scope and proportionality, the server-declared-schema
      inversion, transport analysis, namespace collisions, admission and pinned identity,
      approval semantics, confused-deputy containment, the A-E scope matrix, dependency
      rationale, bounded failure isolation, residual risks, and future mutation-proof
      acceptance criteria. Decision: RE-SCOPE D1 to one explicitly admitted, identity-pinned,
      read-only remote MCP resource server usable from chat with server failure isolated.
      D1 REMAINS BACKLOG pending a future implementation batch. The selected v1 permits no
      MCP tools, no stdio, no local MCP resources, and no MCP-caused local mutation; server
      content cannot enter supervisor routing or native tool context. A future official MCP
      SDK dependency requires exact-version and transitive-dependency review; a hand-rolled
      JSON-RPC client and service-specific native adapter are rejected for D1. No code,
      dependency, configuration, GUI, provider, network, server, README, or ROADMAP change
      was introduced. Proof: 470/470 existing unit tests green with the one known Windows
      symlink-privilege skip; validator 5/5; compileall and diff checks green.

## PHASE D — Research-backed horizon (WHAT only; each is a new threat surface review)
- D1  BACKLOG | MCP support (re-scoped by D1-R, commit 9737c516; pure admission
      foundation D1-I1 DONE in commit 5c337317): one explicitly admitted,
      identity-pinned, read-only remote MCP resource server usable from chat; server
      failure isolated. The selected v1 permits no invokable tools, no stdio, no local
      MCP resources, and no MCP-caused local mutation; server content cannot enter
      supervisor routing or native tool context. D1-I1 adds no transport or dependency
      and is not user-integrated. Review: docs/mcp_integration_review.md. D1-I2 must
      select an exact official MCP SDK version after transitive-dependency review and
      add a read-only transport/chat integration without weakening the D1-I1
      admission, isolation, bounds, redaction, or revocation contracts.
      Accept: one real MCP server usable from chat; server failure isolated. Est 8-15h.
- D3  DONE | 37f03ba2, 7d9d25c6, 518785a9 | Scheduled agents: an instance-local background
      scanner runs the real file categorization/move path at configurable 15-minute,
      30-minute, 1-hour, or 6-hour intervals. Preferences and last-run state survive restart
      in AppData. Generation-specific cancellation is checked between file operations; a
      timed-out stop returns failure; restart creates an isolated generation whose old worker cannot
      commit state or notifications into the replacement.
      Proof: ScheduledScannerTests cover execution, interval validation, persistence,
      cancellation, generation isolation, and isolated overlap; full unit suite green.

## Removed from scope — historical declared-scope decisions
These items were removed from the active roadmap and from declared scope. Their historical titles, acceptance criteria, and estimates are preserved below; DEFERRED is a scope decision, not a failure or evidence of completed work.

- D2  DEFERRED — REMOVED FROM DECLARED SCOPE | Screen-aware automation / PC control: screenshot -> vision analysis -> action.
      Original declaration (BACKLOG): Screen-aware automation: screenshot -> vision analysis -> action. Accept: correct action on a controlled target; refuses ambiguous targets. Est 15-30h + safety batch.
      Rationale: Screen-aware automation / PC control grants synthetic keyboard and mouse input across the ENTIRE desktop, not confined to Incoming/Sorted or the admitted code workspace. Unlike file operations, input has no path, so it cannot be contained by path admission or realpath rules at all. A single model error or hostile provider response could interact with any application, including credential dialogs, browsers, or system settings. This is a strictly larger blast radius than C3's admitted one-file byte replacement, with no equivalent containment mechanism.
- D4  DEFERRED — REMOVED FROM DECLARED SCOPE | Voice control (historical title: Voice activation): wake word + speech-to-text command.
      Original declaration (BACKLOG): Voice activation: wake word + speech-to-text command. Accept: hands-free command end-to-end; false-wake rate tolerable to owner. Est 10-20h.
      Rationale: Voice control requires audio capture (a new privacy surface) plus STT/TTS dependencies (a new trust surface) to duplicate a capability already served by text chat. The C4-ISO host findings also recorded only 568–885 MB available physical memory on an 8 GB host, making model-bearing audio features impractical here independent of the security case.
- D5  DEFERRED — REMOVED FROM DECLARED SCOPE | Phone / remote control (historical title: Phone remote control): authenticated API server.
      Original declaration (BACKLOG): Phone remote control: authenticated API server. Accept: remote command executes only with valid auth; all remote actions sandboxed + logged. Est 10-20h + safety batch.
      Rationale: Phone / remote control requires a network-reachable authenticated control plane. STEWARD already holds filesystem mutation authority (C3) and provider credentials. Exposing that authority to a network endpoint multiplies blast radius: one authentication flaw becomes remote file mutation and credential access. Disproportionate to the convenience for a local desktop tool.

Common thread: each grants authority beyond the application's existing bounded mutation boundary, with no proportionate benefit for a local desktop tool. These decisions follow the same discipline as C4-R and C4-ISO, which deferred execution rather than claim a boundary that could not be proven.

## Cross-cutting v2.1 backlog (not phases; do anytime post-freeze)
- Orphaned retired desktop-control persona cleanup DONE | 2e0fe28e | Removed the active persona and routing surfaces; retained historical PLAN/ROADMAP records and added truthful OUT_OF_SCOPE refusal.
- Conversation memory DONE | 2b9e5031, 9641d1f1, a099c0f2 | Supervisor retains bounded instance-local
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