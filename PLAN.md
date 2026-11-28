# STEWARD v2 — Executable Work Plan (living document)

Read ARCHITECTURE.md first. This file is the ONLY source of truth for scope and status.
Chat logs, memories, and verbal plans are not. If this file and the code disagree:
the code wins on behavior, this file wins on intent — fix this file in the same commit.

## Amendment protocol (how this document changes)
1. Statuses: OPEN | IN-PROGRESS | DONE | DISPUTED | DEFERRED. DONE requires a commit SHA.
2. Add, remove, split, re-scope, or re-estimate ANY item by editing this file directly.
3. Every structural change gets ONE changelog line: date | commit SHA | change | why.
4. No silent scope growth: an item discovered mid-batch moves to a new batch or the
   backlog FIRST, then is worked. (This rule exists because a session once invented
   "Item 5" and padded a report with it.)
5. Estimates are bands, not promises. When reality differs, revise the band and log it.
   Being wrong is fine; being silently wrong is not.
6. The freeze line moves only by explicit owner decision, logged in the changelog.
7. Items may be DEFERRED forever without shame. Deferred is a decision, not a failure.

## Changelog
2026-11-28 | c4bd9906 | DAEMON-1 bounded recursive daemon monitoring: added an opt-in, restart-persistent recursive scope shared by the watchdog daemon and scheduled scanner; enumerated ordinary directories before observer start with depth-8 and 256-directory bounds, deterministic ordering, Sorted/destination and denied-name exclusions, and no symlink/junction following; reported the actual watched roots and bounds from daemon start; bounded FIFO deduplication eviction without evicting in-flight paths; preserved flattening into existing category folders; added 15 focused regressions, seven killed targeted mutants, and ten-run stop/dedup stability matrices; left mutation authority, sandbox, immutable-plan/preflight, journal, tool dispatch, execution policy, dependencies, protected state, and ROADMAP unchanged. | Expand daemon observation scope only while keeping recursive traversal deterministic, bounded, and unable to widen filesystem mutation authority.
2026-11-28 | 02848366 | BATCH MOVE-F1 batch-move binding integrity and cross-plan coverage: replaced ambiguous raw-field hashing with the sibling core's 8-byte big-endian length framing, added the ordered entry count, and bumped the binding version to v2; integrated batch sources and destinations into the existing whole-plan collision authority; added explicit re-verification of every batch_move binding before the first mutation; added five regressions and killed seven targeted mutants; discovery tests increased from 584 to 589 with the one known Windows symlink-privilege skip; added no tool, schema, cleanup, delete, undo, redo, GUI, provider, dependency, protected-state, or ROADMAP change. | Prevent ambiguous bindings and cross-call batch-move collisions or drift from escaping the whole-plan safety boundary.
2026-11-28 | a2ce6946 | MOVE-1 bound batch move: exposed `batch_move` as the thirteenth FileAgent tool with application-owned bounded glob expansion, sandbox confinement, immutable exact-set binding, full-pair dry-run preview, whole-plan collision and drift re-verification, write-ahead journaling per expanded move, and existing individual undo semantics; recursive `**` is refused in v1 and model-supplied path lists are not accepted; discovery tests increased from 573 to 579 with the one known Windows symlink-privilege skip; added no dependency, permission, ROADMAP, protected-state, or permanent-removal change. | Expose batch move without granting model-selected paths or partial-plan execution, while retaining reviewable individual undo.
2026-11-28 | 9e83747c | UNDO-1 non-undoable undo boundary: completed bulk-cleanup journal entries now refuse undo immediately instead of being skipped in favor of an earlier reversible operation; added a real move-then-bulk-cleanup regression proving the refusal and that the earlier moved file remains untouched; left the explicitly tested delete skip policy unchanged and recorded it as a separate backlog decision; discovery tests increased from 572 to 573 with the one known Windows symlink-privilege skip; added no schema, tool, GUI, provider, dependency, ROADMAP, redo, or protected-state change. | Ensure undo never reverses an earlier operation across a newer non-undoable bulk-cleanup entry.
2026-11-28 | 0a9045d3 | BULK-2 bound recycle-bin bulk cleanup: exposed exactly `cleanup_temp_files` and `cleanup_empty_folders` through the twelve-tool FileAgent schema; model calls accept only a sandboxed `directory`, while application enumeration supplies immutable exact candidate, identity-policy, candidate-policy, and SHA-256 bindings; every cleanup binding in a multi-call plan is re-verified before the first removal; drift in added, removed, reordered, identity-changed, root-changed, policy-changed, or hash-mismatched candidates refuses the whole plan; removal is restricted to `send2trash.send2trash`; journal intent precedes removal and records `undoable: False`; `.log` and `.bak` are excluded; empty folders are removed deepest-first; added focused regressions including whole-plan preflight, live-policy drift, undo blocking, AST removal isolation, and spy checks; killed the cleanup re-verification mutant; kept all 572 discovery tests green with the one known Windows symlink-privilege skip; added no permanent-removal primitive, dependency, permission, ROADMAP change, or persistent-state write. | Make bounded bulk cleanup model-dispatchable without granting model-selected paths, permanent deletion, partial-plan drift acceptance, or undo semantics.
2026-11-28 | 9f37d9f, 62ae399 | BULK-1 bounded duplicate hashing and pure bulk-deletion preparation: bounded duplicate hashing to 64 MiB per file and 256 MiB per report with size/mtime/device/inode checks before and after hashing; added an internal read-only enumeration and exact-set binding core with canonical sandbox enforcement, symlink/junction exclusion, traversal/file/candidate/depth/path bounds, deterministic ordering, immutable records, SHA-256 set binding, typed whole-set re-verification refusals, and deepest-first empty-directory closure; documented the six BULK-1 decisions in `docs/bulk_deletion_contract.md`; added six hashing and 28 bulk-core focused regressions, killed four hashing and 20 core targeted mutants, and kept all 562 discovery tests green with the one known Windows symlink-privilege skip; added no chat capability, schema entry, dependency, permission, runtime route, destructive operation, or ROADMAP change. | Make duplicate reports and any future bulk-cleanup approval bounded and reviewable without exposing destructive authority. Future destructive bulk removal is intended to use `send2trash` and requires a separately reviewed approval/execution path; permanent bulk removal is not being exposed.

2026-11-27 | b7619dc3, caab947c | TOOLS-1 bounded filesystem reports and persistent HTTP 404 accounting: exposed exactly three read-only reports (`find_duplicates`, `find_large_files`, and advisory-only `suggest_deletions`) through the active `agents/file_agent.py` schema with strict argument schemas, runtime validation, canonical sandbox paths, symlink/junction exclusion, deterministic ordering, explicit bounds, and no mutation or external-routing path; counted HTTP 404 as a persistent provider failure so the existing five-minute cooldown begins on the fourth failure while 400/422 remain unchanged; documented `agent/core.py` as a non-authoritative compatibility surface with no runtime callers; kept `cleanup_temp_files`, `cleanup_empty_folders`, and `batch_move` outside the active schema as backlog-only destructive utilities; discovery tests increased from 518 to 528 and all 528 passed with the one known Windows symlink-privilege skip. | Provide useful, bounded, read-only filesystem insight without widening destructive authority, and stop a persistently missing provider endpoint from being retried without failure accounting. The final documentation commit SHA is reported in the handoff because a commit cannot contain its own SHA.

2026-11-27 | 5e8c474a, 0348dda5 | ROUTER-1 router failure accounting and provider timing truthfulness: routed persistent connection errors and malformed/non-object JSON through the shared transient-failure path, retained the audited distinct policies for 429, 401/403, 5xx, timeout, other non-2xx, and no-eligible-provider outcomes, renamed the validator's misnamed first-byte latency field to `elapsed_ms` and propagated total completed-request timing through validation and GUI wording, added three focused regressions with shared-increment and elapsed-time-producer mutation proof, and changed no provider schema, dependency, cooldown policy, provider ordering, or HTTP mode; discovery tests increased from 515 to 518 and all 518 passed with the one known Windows symlink-privilege skip. | Make provider failure accounting consistent for transport and response-validity failures, name the measured latency honestly, and derive PLAN publication state from current Git ancestry rather than repeating stale claims.

2026-11-27 | (final commit SHA reported in handoff) | ChromaDB Windows cleanup lifecycle: closed the prior persistent client before agent reinitialization; closed newly created clients when collection initialization fails; made close failures observable while retaining the client reference for diagnosis or retry; added a shared standard-library finalization step after successful close because ChromaDB 1.5.9's Rust-owned SQLite pool can otherwise retain `chroma.sqlite3` after the shared system stops; added seven real-client lifecycle regressions covering both persistent agents, including immediate SQLite-file removal and concurrent delete/recreate; added no dependency, feature, GUI, provider-behavior, or protected-state change; 515/515 discovery tests green with the one known Windows symlink-privilege skip. | Deterministically release Windows file handles during RAG/code-index reinitialization, collection replacement, and teardown without suppressing close errors or reaching into Chroma internals.

2026-11-26 | (final commit SHA reported in handoff) | D1-SURVEY published MCP server survey and admission decision: examined 10 published candidates against all seven D1-I1 rules using official Registry metadata, SEP-2127 server-card material, the MCP tools/resources specifications, and first-party vendor documentation; classified 8 as failing at least one rule and 2 as UNKNOWN, with 0 compatible candidates; recorded that read-only tools still trigger the `tools` capability and that Registry metadata and server cards cannot establish resource enumeration or fingerprint stability; recommended DEFER D1-I2 and retained D1 in BACKLOG; left the owner's server-content product choice open; added no MCP package, transport, configuration, code, feature, GUI, provider-behavior, or protected-state change; 508/508 discovery tests green with the one known Windows symlink-privilege skip. | Prevent D1-I2 implementation from creating a resource path around a server that exposes tools or lacks proven resource semantics while preserving the existing D1 resources-only safety boundary and keeping the content decision with the owner. The one-commit gate prevents embedding this commit's own SHA in `PLAN.md`; the actual final SHA is reported in the handoff rather than represented by a false placeholder.

2026-11-26 | 85038613 | SEC-1 dependency advisory remediation: upgraded cryptography from 43.0.1 to the reviewed non-vulnerable pin 50.0.2 and requests from 2.32.3 to the reviewed fixed pin 2.33.0; recorded the unchanged required transitive closure cffi==2.1.1, pycparser==3.12, certifi==2026.10.23, charset-normalizer==3.5.2, idna==3.20, and urllib3==2.8.0, and added exact cffi and pycparser pins; retained a synthetic Fernet known-answer fixture generated under 43.0.1 and proved byte-exact decryption under 50.0.2; decoupled the cryptography remediation from D1-I2; recorded the confirmed ChromaDB cleanup race in backlog; added no MCP package, transport, feature, GUI, or provider-behavior change; 508/508 discovery tests green with the one known Windows symlink-privilege skip. | Remediate the reviewed cryptography and requests advisories while preserving existing Fernet credential readability and keeping D1-I2 limited to its separately reviewed MCP integration work.
2026-11-26 | 9f1d9ace | D1-DEP MCP dependency and protocol review: documented a 13-section read-only review selecting the official MCP Python SDK at mcp==2.3.0 for a future D1-I2 implementation; recorded the complete 29-package Windows CPython 3.12 binary closure with reviewed artifact hashes, licenses, ownership, and release dates; rejected the narrow requests client and helper/placeholder alternatives; required cryptography==50.0.2 remediation for six current cryptography==43.0.1 advisories; and defined the future hash lock, stdio reachability boundary, transport implications, and D1-I2 acceptance gates; no dependency, lock, configuration, code, runtime, README, or ROADMAP change was introduced; 507/507 tests green with the one known Windows symlink-privilege skip. | Satisfy the binding D1-I2 exact-version/transitive-dependency review prerequisite while keeping D1 BACKLOG and preserving the D1-R official-SDK, read-only, no-tools, no-stdio, no-local-resource boundary.
2026-11-26 | 638d6ffc | D1-I1/D1-R resolution record: the official MCP SDK was selected, exact-version and transitive-dependency review was required before D1-I2, and a non-binding dependency-review backlog line was instructed but omitted from the ledger. | Restore the omitted proposed amendment while preserving the binding review and distinguishing non-binding backlog consideration from the selected SDK transport.
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
2026-11-23 | 9d092fd7, 935a6236 | Added Batch FS-SAFETY-1: reproduce and repair no-op, partial-mutation, partial-folder, and folder-target preflight journal truthfulness; cross-process journal locking was deferred for reviewed design and later implemented in 935a6236. | Reproduce the handoff leads against the current checkout before changing safety behavior.
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
2026-11-22 | 535b9c6d, eef11f9b, ab585a7f | Batch 4c first push carried a syntax break from a partial replace; the repair and documentation-closure commits were subsequently published. | Preserve the actual repair and closure SHAs in the canonical record.
2026-11-22 | 5357cc43 | Batch 4b closed: credential store safety review committed (docs/credential_store_review.md).
2026-11-22 | 3f0ed7d1 | Batch 4a closed: bounded dialog waits (L2 fully closed) and strengthened dedup test; 62 tests green.
2026-11-22 | 33e2b281 | v2.0 FROZEN. README shipped. (amends 1a538464)
2026-11-22 | 7f682d6d | PLAN state repair; app smoke-tested live (failover observed end-to-end); credential store queued to v2.1.
2026-11-22 | b80d2933 | Emergency DB recovery: steward.db restored from C:\temp\db_data.json (16 providers, 4 traces), 16/16 keys decrypted. Invariant corrected: hashes MAY change. Cause: an agent deleted the DB trying to force a hash match.
2026-11-21 | a4408e7f | Document created. Batch 1 (H1,H2,H3,H4,H7) closed and verified.
(future entries above this line, newest first)

## Ground state
Implementation baseline: DAEMON-1 bounded recursive daemon monitoring implementation commit c4bd9906; BATCH MOVE-F1 batch-move binding integrity and cross-plan coverage commit 02848366; MOVE-1 bound batch move implementation commit a2ce6946; UNDO-1 non-undoable undo boundary commit 9e83747c; BULK-2 bound recycle-bin bulk cleanup commit 0a9045d3; BULK-1 bounded duplicate hashing commit 9f37d9f and pure bulk-deletion enumeration/set-binding core commit 62ae399; TOOLS-1 bounded filesystem reports commit b7619dc3 and HTTP 404 provider-failure accounting commit caab947c; ROUTER-1 router failure-accounting commit 5e8c474a and provider timing-truthfulness commit 0348dda5; ChromaDB Windows cleanup lifecycle (final commit SHA reported in handoff); SEC-1 dependency advisory remediation commit 85038613; D1-I1 pure MCP resource admission core commit 5c337317; HYG-1 Patch Review worker and retired-scope cleanup commits 0acf370, 2e0fe28e
Acceptance baseline: DAEMON-1 shared watcher/scheduled-scanner scope with depth-8 and 256-directory pre-start refusals, deterministic ordinary-directory enumeration, Sorted/destination and denied-name exclusions, symlink/junction exclusion, real Windows junction proof, scope reporting, flattened destinations, in-flight-safe FIFO dedup eviction, persisted opt-in preference, seven killed targeted mutants, and ten-run stop/dedup matrices; BATCH MOVE-F1 length-framed v2 binding with ordered entry count, ambiguity regression, one whole-plan collision authority for batch sources and destinations, explicit re-verification of every batch_move call before the first mutation, four cross-call zero-move regressions, and seven killed targeted mutants; MOVE-1 thirteen-tool dispatch, strict app-owned pattern/destination arguments, bounded deterministic expansion, immutable exact-set binding, full-pair preview, pattern and link refusals, whole-plan collision and drift refusal, journal-before-move ordering, and individual undo regressions; UNDO-1 immediate refusal at a completed bulk-cleanup entry with the earlier move proven untouched and mutation proof; BULK-2 twelve-tool dispatch, argument refusal, app-owned binding, whole-plan drift refusal, live-policy drift, recycle-bin-only execution, deepest-first empty-folder ordering, journal-before-removal, undo blocking, and mutation-proof regressions; BULK-1 duplicate hashing per-file/cumulative budgets and race guards plus pure-core canonical sandbox, link exclusion, traversal bounds, deterministic ordering, immutable records, exact-set binding, typed whole-set refusal, non-mutation, and twelve-tool dispatch regressions; TOOLS-1 strict schema/runtime validation, sandbox refusal, traversal, serialization, finite-number, advisory-only, and HTTP 404 threshold regressions; ROUTER-1 transient-failure and total-elapsed-time regressions; ChromaDB persistent-agent lifecycle regressions and related RAG/code-index suite; SEC-1 cross-version Fernet known-answer regression and focused credential-path suite; 604/604 discovery tests green
Review baseline: D1-R MCP integration safety review commit 9737c516
Survey baseline: D1-SURVEY published MCP server survey and DEFER decision; final commit SHA is reported in the handoff because a commit cannot contain its own SHA
Dependency review baseline: D1-DEP MCP dependency and protocol review commit 9f1d9ace
Dependency remediation baseline: SEC-1 cryptography and requests advisory remediation commit 85038613
Execution review baseline: C4-R execution safety review commit 8f3cb0da
Isolation research baseline: C4-ISO Windows isolation research and decision commit 3afe56aa
Documentation baseline: C4 documentation reconciliation commit 7b427437
Suite: 604/604 unit tests green with one expected Windows symlink-privilege skip; validator 5/5; compileall and diff checks green
Roadmap denominator (scope removal only): whole ROADMAP 22/27 checked (81.48%) before -> 22/24 checked (91.67%) after; active Phase D 1/5 checked (20%) before -> 1/2 checked (50%) after. The completion percentage increased only because scope was removed, not because work was completed.
Scope declaration baseline: SCOPE-R1 documentation-only amendment commit e7a462d2; HYG-1 commit 2e0fe28e subsequently removed the orphaned active persona/routing without adding capability; D1-R commit 9737c516 re-scoped the still-BACKLOG D1 MCP item to one read-only remote resource server without adding capability.
Push state at documentation verification (2026-11-28, after implementation commit, before this closure commit): `origin/main` resolves to `64c8f5c6778eb7337a944dbbd5bc9a16f3873efb`. Fresh `git merge-base --is-ancestor` checks show prior baseline commits `02848366862ad8e0d799756de9e13adb0cb31c4a` and `146dd7151ccebdbf2960add06b03deb9b3639273` are published ancestors of `origin/main` (exit 0 each). DAEMON-1 implementation commit `c4bd9906351fa7f316c6869b988f91f2e2ba1800` and current `HEAD` are not ancestors of `origin/main` (exit 1 each). This documentation closure is also local until pushed.
Publication-state convention: never copy a prior push-state claim forward. At every verification, resolve `origin/main` and current `HEAD`, run `git merge-base --is-ancestor <sha> origin/main` for every named commit and for current `HEAD`, and record each exit result (0 = published ancestor, 1 = not an ancestor, any other exit = verification failure). Re-derive the paragraph from those results at the time of writing.
Bare-subject deviation ledger: `8e8d4f34`, `9dbf774d`, and `96dcfe14` are confirmed
pushed ancestors with bare commit subjects and no structured Problem/Design/Fix/Impact/
Tests/Gates body. They are not rewritten because they are already public history; C7 commit
`883347bf` and its documentation closure use the required structured body.
Additional commit-body deviation: `5c337317` and `638d6ffc` used a merged `Tests/Gates`
section instead of six separate sections; their content is present, but the structure
deviated. The subject of `638d6ffc` says "open dependency decision" while its body and PLAN
correctly record the SDK as selected. Public history is not rewritten.
MOVE-1 implementation commit `a2ce6946` reports `573 -> 579` discovery tests in its body,
while the later documentation closure and current handoff report 584; the binding fix added
tests after the implementation body was drafted. Inspection confirms that `a2ce6946` does
contain a separate `Gates` section and all six required section headings, so there is no
missing-Gates deviation to record for that commit. The stale count is retained as a published
commit-body deviation rather than rewriting history.
Commit-body convention: every commit body carries SIX SEPARATE sections — Problem / Design /
Fix / Impact / Tests / Gates. Tests reports counts and RED->GREEN/mutation evidence; Gates
reports the gate commands and results. Do not merge them.
Persistent state: `%APPDATA%\STEWARD`; legacy repository-root files are copied, never moved or overwritten.
Invariants: The agent must never write to, delete, or recreate steward.db or secret.key. Their hashes MAY change during normal application use; a changed hash is NOT a defect; helper scripts never in repo.
Tool split: Qwen agent-mode sandbox proves safety fixes off-tree; human applies + verifies; Cline/Kimi/Antigravity for volume. Never two writers on one file.

## Implemented
- DAEMON-1 Bounded recursive daemon monitoring — DONE | c4bd9906
  recursive observation is explicitly enabled and persisted, with the default remaining
  non-recursive. The daemon and scheduled scanner share one deterministic scope contract that
  enumerates ordinary directories before observer start, caps depth at 8 and directory count at
  256, refuses overflow before observation, excludes Sorted/destination roots and denied names,
  and never follows symlinks or Windows junctions. Each enumerated root is observed with
  `recursive=False`; daemon start reports the actual roots and bounds. Nested files flatten into
  existing category folders. FIFO dedup eviction is bounded and protects in-flight paths.
  Proof: 15/15 focused; 22/22 legacy scheduler; seven targeted mutants killed; stop responsiveness
  and dedup eviction each passed 10/10 consecutive runs; full discovery passed 604/604 with one
  expected skip; validator 5/5; compileall and diff checks green. The active dispatch set remains
  exactly thirteen tools, and mutation authority, sandbox, plan/preflight, journal, execution
  policy, dependencies, protected state, and ROADMAP are unchanged.
- BATCH MOVE-F1 — Batch-move binding integrity and cross-plan coverage — DONE | 02848366
  The v2 batch-move binding mirrors the bulk-deletion core's 8-byte big-endian length framing
  and hashes the ordered entry count, so field boundaries and set size cannot alias; previously
  constructed v1 bindings refuse rather than silently mismatch. The existing whole-plan
  preflight is the single collision authority and now reserves batch sources and destinations
  against every other call. `_reverify_batch_move_plan(plan)` re-verifies every batch_move
  binding before the first mutation. Proof: focused exposure suite 16/16; full discovery
  increased from 584 to 589 and passed 589/589 with the one known Windows symlink-privilege
  skip; four cross-call regressions refused with zero moves; seven targeted mutants were each
  killed by their named regression and GREEN after exact-byte restoration; validator 5/5;
  compileall and diff checks green. The active dispatch set remains exactly thirteen tools.
- MOVE-1 Bound batch move — DONE | a2ce6946
  `batch_move` is the thirteenth active FileAgent tool. The model supplies only a sandboxed
  `source_pattern` and `destination_folder`; application-owned expansion produces a bounded,
  deterministic exact set of source→destination pairs and excludes symlinks/junctions.
  The immutable binding covers canonical paths, identities, and hashes, and is re-verified before
  the first move. The stored hash is recomputed from the exact entries during deserialization,
  so forged or mutated bindings fail closed. Preview enumerates every pair; whole-plan occupied,
  duplicate, and file/directory conflicts refuse before mutation. Recursive `**` is refused in v1.
  Each expanded move uses the existing write-ahead journal and no-overwrite publication, so each
  move retains individual undo semantics. Proof: focused exposure regressions plus full discovery
  584/584 with the one known
  Windows symlink-privilege skip; validator 5/5; compileall and diff checks green. The active
  dispatch set is exactly thirteen tools; no dependency, permission, ROADMAP, protected-state, or
  permanent-removal change was added.
- BULK-2 Bound recycle-bin bulk cleanup — DONE | 0a9045d3
  exactly two cleanup tools are model-dispatchable. Model arguments are restricted to a
  sandboxed `directory`; application enumeration supplies canonical root, ordered candidates,
  identity/candidate policies, and SHA-256 binding. Every cleanup binding in a multi-call plan is
  re-verified before the first removal; added, removed, reordered, identity-changed, root-changed,
  policy-changed, or hash-mismatched candidates refuse the whole plan. `.log` and `.bak` are
  excluded, empty folders are deepest-first, and removal uses only `send2trash.send2trash`.
  Journal intent precedes removal, metadata records `undoable: False`, and undo refuses
  immediately at the completed bulk-cleanup entry without consuming an earlier unrelated
  operation. Proof: focused exposure/core/phase suites 255/255; full discovery
  572/572 with the one known Windows symlink-privilege skip; removal of the re-verification guard
  made all seven drift classes reach `send2trash`, proving the mutant was killed; validator 5/5;
  compileall and diff checks green. The active dispatch set is exactly twelve tools; no permanent
  removal, dependency, permission, ROADMAP change, or persistent-state write was added.
- UNDO-1 Refuse undo at a non-undoable entry — DONE | 9e83747c
  A completed bulk-cleanup entry now refuses undo immediately and cannot be skipped in favor
  of an earlier reversible operation. A real move followed by a completed non-undoable
  bulk-cleanup entry proves that the refusal is returned and the earlier moved file remains
  untouched at its destination. The regression was RED before the fix and GREEN afterward;
  restoring the old `continue` made it RED again. The delete branch remains unchanged because
  `Batch2BTests.test_delete_entry_skipped_and_never_marked_undone` explicitly requires undo
  to skip a delete and reverse an earlier move. Proof: focused undo/delete set 4/4; full
  discovery increased from 572 to 573 and passed 573/573 with the one known Windows
  symlink-privilege skip; validator 5/5; compileall and diff checks green. No schema, tool,
  GUI, provider, dependency, ROADMAP, redo, or protected-state change was made.
- UNDO-1-POLICY  BACKLOG | Decide whether a successful delete entry should refuse undo immediately instead of preserving the explicitly tested skip-and-reverse-earlier-operation policy; `test_phase0_phase_a.py:1800` asserts that undo skips delete and undoes an earlier move; no code change is authorized until that policy is decided separately.
- BULK-1 Bounded duplicate hashing and pure bulk-deletion preparation — DONE | 9f37d9f, 62ae399
  duplicate hashing is bounded to 64 MiB per file and 256 MiB per report and verifies size,
  `mtime_ns`, device, and inode before and after hashing, skipping changed, inaccessible,
  oversized, and cumulative-budget files truthfully. A new internal read-only core enumerates
  temporary-file candidates or the deepest-first empty-directory closure, enforces canonical
  sandbox roots, excludes symlinks/junctions, and refuses whole enumerations on path-length,
  depth, file-count, candidate-count, or traversal-I/O failures. Frozen records bind the exact
  ordered set by canonical path, size, and `mtime_ns`; the SHA-256 binding also covers the
  identity policy, root, count, kind, and order. Re-verification refuses the whole binding on
  added, removed, changed, reordered, root, policy, or hash drift. Proof: 6/6 hashing, 28/28
  bulk-core, 34/34 combined focused, and 562/562 discovery tests green with the one known
  Windows symlink-privilege skip; validator 5/5; compileall and diff checks green; four
  hashing and 20 core targeted mutants killed. The core is not imported or exposed by the
  active FileAgent dispatch path, which remains exactly ten tools; no destructive operation,
  chat capability, schema entry, dependency, permission, or runtime route was added. The six
  decisions are documented in `docs/bulk_deletion_contract.md`.
- TOOLS-1 Bounded filesystem reports and persistent HTTP 404 accounting — DONE | b7619dc3, caab947c
  the active FileAgent now exposes exactly three bounded read-only reports: duplicate-file
  detection, large-file detection, and advisory-only deletion suggestions. Strict schemas and
  runtime validation reject extra or missing arguments and non-finite thresholds; paths are
  canonicalized and sandboxed before dispatch; traversal excludes symlinks/junctions and is
  deterministic. Bounds are 1,000 files visited, depth 8, 50 result entries, 32,768 serialized
  bytes, 1,024-character directory paths, 10,240 MB size thresholds, and 3,650-day age thresholds.
  The reports never mutate files or invoke external routing. HTTP 404 now increments provider
  failure count and starts the existing five-minute cooldown on the fourth failure; 400/422 retain
  their prior policy. Proof: 19/19 related tests and 528/528 discovery tests green with the one
  known Windows symlink-privilege skip; validator 5/5; compileall and diff checks green. The
  legacy `agent/core.py` StewardAgent is non-authoritative and has no runtime callers; bulk
  destructive utilities (`cleanup_temp_files`, `cleanup_empty_folders`, and `batch_move`) remain
  outside the active schema as backlog-only items.
- ChromaDB Windows cleanup lifecycle — DONE | (final commit SHA reported in handoff)
  persistent RAG and code-index agents now close the prior ChromaDB client before reinitialization,
  close newly created clients after initialization failures, and expose close failures instead of
  suppressing them. A shared standard-library finalization step after successful close releases
  ChromaDB 1.5.9's Rust-owned SQLite pool on Windows without using Chroma internals. Proof: seven
  real-client lifecycle regressions for both agents, 40 related RAG/code-index tests, and 515/515
  discovery tests green with the one expected Windows symlink-privilege skip.
- SEC-1 Dependency advisory remediation — DONE | 85038613
  upgraded the exact direct pins `cryptography==43.0.1` -> `cryptography==50.0.2` and
  `requests==2.32.3` -> `requests==2.33.0`; pinned the unchanged required transitive
  closure; retained a synthetic Fernet known-answer fixture generated under 43.0.1;
  and proved byte-exact decryption under 50.0.2. No MCP package, transport, feature,
  GUI, or provider-behavior change was introduced. Proof: 11/11 focused credential-path
  tests and 508/508 discovery tests green with the one known Windows symlink-privilege
  skip; validator 5/5; compileall and diff checks green.
- D1-DEP MCP dependency and protocol review — DONE | 9f1d9ace
  read-only 13-section dependency decision selecting the official MCP Python SDK at
  `mcp==2.3.0` for a future D1-I2 implementation. The review records the complete
  29-package Windows CPython 3.12 binary closure, reviewed wheel hashes, licenses,
  ownership, release dates, and exact-version advisory status; rejects the narrow
  `requests` client and helper/placeholder alternatives; requires the current
  `cryptography==43.0.1` pin to be replaced by `cryptography==50.0.2`; and defines
  the future platform lock, transport/import boundary, and D1-I2 acceptance gates.
  No dependency, lock, configuration, code, transport, chat surface, or runtime
  capability was added; D1 remains BACKLOG pending D1-I2.
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

## BATCH UNDO-1 — refuse undo at a non-undoable entry
Files: agents/file_agent.py, test_bulk_cleanup_exposure.py, ARCHITECTURE.md, README.md, PLAN.md
- UNDO-1  DONE | 9e83747c | A completed bulk-cleanup entry now refuses undo immediately
  instead of being skipped in favor of an earlier reversible operation. A real move followed by
  a completed `undoable: False` bulk-cleanup entry proves that the refusal is returned and the
  earlier moved file remains untouched at its destination. The regression was RED before the fix,
  GREEN afterward, and RED again when the old `continue` was restored. The delete branch remains
  unchanged because `test_phase0_phase_a.py:1800` explicitly requires undo to skip a delete and
  reverse an earlier move; that policy is recorded as one backlog line. Proof: focused undo/delete
  set 4/4; full discovery increased from 572 to 573 and passed 573/573 with the one known Windows
  symlink-privilege skip; validator 5/5; compileall and diff checks green.

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
      is published to origin at `fc3cc0ee` and confirmed as an ancestor of `origin/main`.

### FS-S5 closure handoff ledger
- Verified baseline: `eaee322b`. The pre-existing FS-S5 implementation `935a6236` and closure
  `eaee322b` are confirmed published ancestors of `origin/main`; the stale local-not-pushed
  claim is corrected here.
- Encoding finding: confirmed, not disputed. Exact affected literals were `agents/file_agent.py`
  lines 683, 705, 790, 810, 1304, 1306, 1310, 1314, 1342, 1344, and 1499 before repair.
- Repair: `fc3cc0ee` restores `→` in those 11 literals only and adds one bounded tracked-Python
  regression. BOMs and line endings were not altered.
- Push state: `fc3cc0ee` and plan-reconciliation commit `9b8ee32e` are published to origin at
  their respective SHAs and are ancestors of `origin/main`.

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
  selected D1 transport choice; its exact-version and transitive-dependency review
  is complete in D1-DEP commit 9f1d9ace and remains a prerequisite for installation
  in D1-I2.
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
      D1 REMAINS BACKLOG pending D1-I2. The selected v1 permits no
      MCP tools, no stdio, no local MCP resources, and no MCP-caused local mutation; server
      content cannot enter supervisor routing or native tool context. A future official MCP
      SDK dependency requires exact-version and transitive-dependency review; a hand-rolled
      JSON-RPC client and service-specific native adapter are rejected for D1. No code,
      dependency, configuration, GUI, provider, network, server, README, or ROADMAP change
      was introduced. Proof: 470/470 existing unit tests green with the one known Windows
      symlink-privilege skip; validator 5/5; compileall and diff checks green.

## BATCH D1-SURVEY — published MCP server survey and admission decision (DONE)
Files: docs/mcp_server_survey.md, PLAN.md
Survey document: docs/mcp_server_survey.md
- D1-SURVEY  DONE | (final commit SHA reported in handoff) | Completed a
      documentation-only survey of 10 published MCP server candidates against all seven
      D1-I1 admission rules. Evidence came from the official MCP Registry API and its
      `server.json` metadata, SEP-2127 server-card material, the MCP tools/resources
      specifications, and first-party vendor documentation; no candidate MCP endpoint
      was contacted, initialized, probed, or listed from. Eight candidates fail at least
      one rule and two remain UNKNOWN; compatible candidates: 0. Read-only wording does
      not make a tool server admissible because MCP servers that support tools MUST
      declare the `tools` capability. Registry metadata and SEP-2127 cards cannot prove
      runtime resources, complete same-origin URI enumeration, or fingerprint stability.
      Decision: DEFER D1-I2 and keep D1 in BACKLOG until one candidate has affirmative
      evidence for all seven rules and the owner separately chooses whether its published
      content is useful to STEWARD. No dependency, lock, configuration, code, transport,
      server, chat/GUI surface, provider behavior, README, ROADMAP, protected state, or
      runtime capability was introduced. Proof: 508/508 discovery tests green with the
      one known Windows symlink-privilege skip; validator 5/5; compileall and diff checks
      green. The one-commit gate prevents this record from embedding the SHA of the
      commit that contains it; the actual final SHA is reported in the handoff rather
      than represented by a false placeholder.

## BATCH D1-DEP — MCP dependency and protocol review (DONE)
Files: docs/mcp_dependency_review.md, PLAN.md
Review document: docs/mcp_dependency_review.md
- D1-DEP  DONE | 9f1d9ace | Completed a read-only, 13-section MCP dependency and
      protocol review covering scope, the required JSON-RPC/MCP lifecycle and transport
      surface, the official SDK versus a narrow `requests` client and helper/placeholder
      alternatives, the complete 29-package Windows CPython 3.12 binary closure,
      licenses/ownership/release dates, exact-version advisory status, transport and
      import implications, the future D1-I2 requirement/lock plan, final rationale,
      acceptance criteria, and residual limitations. Decision: select the official
      `mcp==2.3.0` SDK for a future D1-I2 implementation. Candidate B, a hand-written
      client over existing `requests==2.32.3`, is rejected because it transfers protocol
      correctness, modern/legacy negotiation, session/SSE, and hostile-input maintenance
      to STEWARD and inherits two advisories affecting the current requests pin.
      Candidate C is rejected because `httpx-sse` is only an SSE helper and
      `mcp-client==0.0.0` is an empty Python-3.13-only placeholder. The reviewed
      `cryptography==43.0.1` pin was affected by six distinct advisory records. That
      separate remediation condition is now completed by SEC-1 commit `85038613`, which
      replaced it with `cryptography==50.0.2` and proved cross-version Fernet
      compatibility; D1-I2 must not re-apply the cryptography remediation.
      D1-I2 must use a complete exact-version/hash platform lock, repeat advisory checks,
      import only the SDK client API, and prove that no stdio configuration or process
      launch is reachable; the upstream eager stdio import means module absence from
      `sys.modules` is not a valid boundary test. D1 REMAINS BACKLOG. No dependency,
      lock, configuration, code, transport, server, chat/GUI surface, README, ROADMAP,
      protected state, or runtime capability was introduced. Proof: 507/507 discovery
      tests green with the one known Windows symlink-privilege skip; validator 5/5;
      compileall and diff checks green; structural checks confirm 13 ordered sections,
      29 unique closure versions/hashes, 29 linked governance rows, and a contiguous
      S1-S36 source register with all citations resolved and no append marker.

## BATCH SEC-1 — dependency advisory remediation (DONE)
Files: requirements.txt, test_fernet_compatibility.py, PLAN.md
- SEC-1  DONE | 85038613 | Replaced `cryptography==43.0.1` with
  `cryptography==50.0.2` and `requests==2.32.3` with `requests==2.33.0`. The
  reviewed cryptography wheel for Windows CPython 3.12 x64 was verified as
  `cryptography-50.0.2-cp311-abi3-win_amd64.whl` with SHA-256
  `7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c`.
  The complete resolved required transitive closure was recorded as
  `cffi==2.1.1`, `pycparser==3.12`, `certifi==2026.10.23`,
  `charset-normalizer==3.5.2`, `idna==3.20`, and `urllib3==2.8.0`; `cffi` and
  `pycparser` received exact requirements pins, while the remaining transitive
  versions were unchanged. The pip dry-run
  environment delta contained only the two direct changes and no unexpected package.
  Exact-version OSV queries immediately before installation returned zero advisories
  for every new exact version and the complete relevant transitive closure.
  Remediated cryptography advisories: GHSA-79v4-65xg-pq4g,
  GHSA-r6ph-v2qm-q3c2, GHSA-m959-cc7f-wv43, GHSA-537c-gmf6-5ccf,
  GHSA-jwv3-5hgf-82ww, and GHSA-m2h6-j472-rp4c. Remediated requests advisories:
  GHSA-9hjg-9r4m-mvj7 and GHSA-gc5v-m9x4-r6x2.
  Reachability analysis: GHSA-r6ph-v2qm-q3c2 (SECT subgroup validation),
  GHSA-m959-cc7f-wv43 (peer-name DNS constraints), GHSA-jwv3-5hgf-82ww
  (duplicate-intermediate X.509 path building), and GHSA-m2h6-j472-rp4c
  (wildcard permittedSubtrees) are not plausibly reachable because STEWARD uses
  cryptography only for Fernet symmetric encryption and does not perform X.509 path
  validation or SECT/ECDSA/ECDH operations. The broader OpenSSL-in-wheel records are
  also not plausibly reachable through that usage: GHSA-79v4-65xg-pq4g requires TLS
  raw-public-key handshakes, while GHSA-537c-gmf6-5ccf concerns the affected
  PKCS#7/S/MIME, CMS, and related OpenSSL APIs in the June 2026 advisory family;
  STEWARD invokes none of those APIs, and ordinary Fernet AES-CBC/HMAC use is not
  the affected mechanism. These reachability findings do not justify retaining the
  affected pins. On the requests side, GHSA-9hjg-9r4m-mvj7 is plausibly reachable
  if a user-configured provider URL is malicious and the HTTP path honors `.netrc`;
  the upgrade removes that exposure. GHSA-gc5v-m9x4-r6x2 is not plausibly reachable
  because it affects direct callers of `extract_zipped_paths()`, which STEWARD does
  not call. This reachability analysis affects urgency only, not the remediation
  decision.
  Cross-version Fernet proof: before installation, cryptography 43.0.1 generated the
  synthetic key and token retained as clearly labeled test constants; after
  installation, cryptography 50.0.2 decrypted that token to byte-identical plaintext
  `SEC-1 synthetic Fernet compatibility plaintext; not a credential.` The expected
  and decrypted byte strings were equal. The retained regression keeps this known
  answer permanently in the suite. Existing credential paths remain green: dual-read
  legacy fallback, shared-credential migration and rollback, credential rotation, and
  decryption-error handling. Proof: 11/11 focused credential tests; 508/508 discovery
  tests green with the one known Windows symlink-privilege skip; validator 5/5;
  compileall and diff checks green. No MCP package, transport, feature, GUI, provider
  behavior, review-document rewrite, or ROADMAP change was introduced.

## BATCH TOOLS-1 — bounded filesystem reports and persistent HTTP 404 accounting (DONE)
Files: agent/tools.py, agents/file_agent.py, core/router.py, test_phase0_phase_a.py, ARCHITECTURE.md, README.md, PLAN.md
- TOOLS-1  DONE | b7619dc3, caab947c | The active `agents/file_agent.py` provider schema exposes
      exactly three bounded read-only reports: `find_duplicates`, `find_large_files`, and
      `suggest_deletions`. Their schemas reject additional properties and runtime validation
      rejects missing, unexpected, non-finite, or out-of-range arguments. Directory paths are
      canonicalized and confined to Incoming/Sorted before threshold validation or dispatch;
      traversal excludes symlinks/junctions, sorts deterministically, and exposes explicit
      truncation/error markers. Bounds are 1,000 files visited, depth 8, 50 result entries,
      32,768 serialized bytes, 1,024-character directory paths, 10,240 MB size thresholds, and
      3,650-day age thresholds. `suggest_deletions` is advisory only: it never deletes, schedules
      deletion, approves a plan, or invokes external routing. HTTP 404 now uses the established
      persistent provider-failure path, so the five-minute cooldown begins on the fourth failure;
      the audited 400/422 policy is unchanged. The legacy `agent/core.py` StewardAgent is
      non-authoritative and has no runtime callers; the active FileAgent is the provider/dispatch
      authority. `cleanup_temp_files`, `cleanup_empty_folders`, and `batch_move` remain outside
      the active schema as backlog-only destructive utilities. Proof: 19/19 related tests and
      528/528 discovery tests green with the one known Windows symlink-privilege skip; validator
      5/5; compileall and diff checks green.

## BATCH ROUTER-1 — router failure accounting and honest provider timing (DONE)
Files: core/router.py, core/validator.py, gui/settings_tab.py, test_phase0_phase_a.py, ARCHITECTURE.md, README.md, PLAN.md
- ROUTER-1  DONE | 5e8c474a, 0348dda5 | Corrected the two inconsistent transient
  branches: persistent connection errors and malformed/non-object JSON now use the same
  `_register_transient_failure` path as 5xx and request timeouts, increment the provider's
  `failure_count`, and start the existing five-minute cooldown after the fourth failure.
  The branch audit retained intentional existing policies: 429 applies `Retry-After` cooldown
  without a failure increment; 401/403 deactivate without a failure increment or cooldown;
  5xx and timeout increment and cool down after the fourth failure; other non-2xx responses
  do not mutate provider failure state; and no eligible provider means there is no provider
  record to mutate. Provider ordering, `providers.speed_score_ms`, the database schema,
  dependencies, cooldown duration/threshold, and HTTP mode remain unchanged.
  Separately, the validator's misnamed first-byte latency field was renamed to `elapsed_ms` and propagated
  through `validate_provider`; the non-streaming health check measures total completed-request
  elapsed time, not time to first byte or time to first token, and the GUI says "total request".
  Proof: the discovery suite grew from 515 to 518 tests; persistent-connection-error and
  invalid-JSON regressions were RED before the shared increment and GREEN afterward, and
  targeted mutation removed the shared `failure_count` increment to prove both regressions
  detect it. A measurement regression was RED without the `elapsed_ms` producer and GREEN
  with it, and mutation removed that producer to prove the regression detects it. Final proof:
  518/518 discovery tests green with the one known Windows symlink-privilege skip; validator
  5/5; compileall and diff checks green.

## PHASE D — Research-backed horizon (WHAT only; each is a new threat surface review)
- D1  BACKLOG | MCP support (re-scoped by D1-R, commit 9737c516; pure admission
      foundation D1-I1 DONE in commit 5c337317; dependency review D1-DEP DONE in
      commit 9f1d9ace; published server survey D1-SURVEY DONE with final commit SHA
      reported in the handoff): one explicitly admitted, identity-pinned, read-only remote
      MCP resource server usable from chat; server failure isolated. The selected v1 permits
      no invokable tools, no stdio, no local MCP resources, and no MCP-caused local
      mutation; server content cannot enter supervisor routing or native tool context.
      D1-I1 adds no transport or dependency and is not user-integrated. Reviews:
      docs/mcp_integration_review.md, docs/mcp_dependency_review.md, and
      docs/mcp_server_survey.md. D1-DEP selects the official `mcp==2.3.0` SDK for a
      future D1-I2 implementation. D1-SURVEY examined 10 published candidates and found
      0 compatible: 8 fail at least one D1-I1 rule and 2 remain UNKNOWN. D1-I2 is DEFERRED
      until one candidate has affirmative published evidence for all seven rules and the
      owner separately chooses its useful server content. Its separate cryptography
      remediation condition was completed in SEC-1 commit `85038613`, which replaced
      `cryptography==43.0.1` with `cryptography==50.0.2` and proved cross-version Fernet
      compatibility; D1-I2 must not re-apply that remediation. A reopened D1-I2 remains
      responsible for its own complete exact-version/hash platform lock, repeated advisory
      checks, and proof that no stdio configuration or process launch is reachable. It must
      add a read-only transport/chat integration without weakening the D1-I1 admission,
      isolation, bounds, redaction, or revocation contracts.
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

## BATCH BULK-1 — bounded duplicate hashing and pure bulk-deletion preparation (DONE)
Files: agent/tools.py, agent/bulk_deletion_core.py, test_hashing_read_budget.py, test_bulk_deletion_core.py, docs/bulk_deletion_contract.md, ARCHITECTURE.md, README.md, PLAN.md
- BULK-1  DONE | 9f37d9f, 62ae399 | Six binding decisions are recorded in
      `docs/bulk_deletion_contract.md`: (1) expose preparation only, never execution;
      (2) canonicalize and sandbox the root and allowed roots; (3) use bounded, link-free
      traversal and refuse the whole result on I/O or bound failure; (4) retain deterministic
      temporary-file and deepest-first empty-directory ordering; (5) use immutable records and
      an SHA-256 hash of the exact ordered set and identity policy; and (6) re-verify the whole
      binding with typed refusals for any membership, identity, order, root, policy, or hash
      discrepancy. Future destructive exposure is not part of BULK-1 and remains backlog-only.

## Cross-cutting v2.1 backlog (not phases; do anytime post-freeze)
- ChromaDB cleanup race on Windows | DONE | (final commit SHA reported in handoff) | Fixed at the persistent-agent boundary for both RAG and code indexing. Reinitialization closes the existing client before creating its successor; initialization rollback closes a newly created client; close failures are observable and retain the client reference; and a shared post-close finalization pass releases ChromaDB 1.5.9's Rust-owned SQLite pool on Windows. Real-client regressions prove immediate `data_level0.bin` and `chroma.sqlite3` release after delete/recreate and teardown. No Chroma private internals, subprocess boundary, dependency, or protected-state change was introduced.
- Orphaned retired desktop-control persona cleanup DONE | 2e0fe28e | Removed the active persona and routing surfaces; retained historical PLAN/ROADMAP records and added truthful OUT_OF_SCOPE refusal.
- Conversation memory DONE | 2b9e5031, 9641d1f1, a099c0f2 | Supervisor retains bounded instance-local
  FILE_OP context; general Cortex chat retains at most 6 turns, 12,000 total characters, and
  4,000 characters per message. Clearing chat erases general-chat memory, invalidates pending
  or in-flight file previews, and rejects stale responses/UI continuations across all specialist
  paths.
- pytest migration of the suite
- Bulk destructive filesystem exposure | BACKLOG | BULK-1 now provides a pure, bounded
  preview/set-binding core, but `cleanup_temp_files`, `cleanup_empty_folders`, and `batch_move`
  remain intentionally absent from the active FileAgent schema. Any future destructive tool
  requires a separately reviewed `send2trash`-based approval/execution path; permanent bulk
  removal is not being exposed.
- Windows installer / packaging
- Broader test coverage beyond safety (router perf, GUI smoke)

## Rules of engagement
1. Work ONLY the batch or phase named in your prompt.
2. RED -> fix -> GREEN, pasting both outputs. Safety items also get mutation proof.
3. Security tests enter via execute_pending_plan() with a hostile plan, never convenience methods.
4. No invented items. Disputed items are marked DISPUTED with exact source lines.
5. Update statuses here in the closing commit; record the actual commit SHA; log structural changes.
6. Context death: commit proven work, write the handoff ledger INTO THIS FILE.
7. Environment: PowerShell (no &&, no rg, no tail), unittest not pytest, BOM files need
   utf-8-sig, protected files never modified, helper scripts outside the repo.

## Session start (the whole preamble)
Read ARCHITECTURE.md and PLAN.md. Work ONLY <BATCH-or-PHASE>. Follow Rules of engagement.
Update PLAN.md statuses and changelog in your closing commit.
