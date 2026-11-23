# STEWARD — C3 AST Patch Safety Review

**Document status:** Complete design/threat review; no implementation authorized
**Review batch:** C3-R
**Decision:** **RE-SCOPE**, then proceed only in a future implementation batch
**C3 status after this review:** **BACKLOG**
**C4 status after this review:** **BACKLOG**
**Baseline reviewed:** `42c4245c03f26d6f0313bc16407b684f634ded17` (`docs(code): reconcile phase c7 implementation state`)
**Scope of this document:** design and safety review only; no code, tests, dependencies, execution surface, or behavior change

---

## 1. Scope and non-goals

### 1.1 In scope

C3 is the future ability to **apply a user-approved structured patch to existing source files**. A successful future C3 implementation will:

1. select an explicitly user-authorized code workspace;
2. validate a strict structured patch and bind it to exact source bytes;
3. show the exact resulting diff;
4. require a single-use approval bound to the immutable patch artifact;
5. apply only the approved bytes to admitted existing files; and
6. journal enough evidence to support recovery and content-edit undo/redo.

This review determines whether that future mutation surface can be bounded safely. It does not implement that surface.

### 1.2 Explicit non-goals and ownership boundaries

- **C3 does not execute patched code.** It does not import the target module, run the target program, invoke a test runner, invoke a linter, evaluate the patch, or start a subprocess. Parsing source with `ast` is analysis, not execution.
- **C3 does not lint or test patched code.** Syntax parsing and structural validation are mutation preconditions, not linting or test execution.
- **C4 owns execution.** PLAN defines C4 as a self-healing `lint/run -> read stderr -> patch -> retry` loop with its own hard iteration bound and sandbox (`PLAN.md:295-320`, Phase C gate and C3/C4 items). C4 must retain a **separate safety gate**; C3 approval is not C4 execution approval.
- C3 does not create files, delete files, rename files, or move files. Its first implementation is limited to content edits of admitted existing files.
- C3 does not modify the existing Incoming/Sorted sandbox, reuse it as a write root, or silently widen it.
- This review adds no implementation, tests, dependencies, UI, or runtime behavior.

### 1.3 Verified starting point

- C2 currently validates a strict plan blueprint, persists an app-owned immutable artifact, and uses a single-use ID-bound approval to start a **text-only** Syntax request (`agents/plan_agent.py:81-147`, `validate_blueprint`; `agents/plan_agent.py:213-267`, `PlanAgent.approve_plan` and `PlanAgent.build_plan`). Its builder prompt explicitly says Syntax has no tools and must not claim to edit, apply, run, or test files (`agents/plan_agent.py:157-160`, `BUILDER_PROMPT`).
- C2 targets remain informational and never reach FileAgent (`PLAN.md:88-94`, Phase C2 implemented record; `ARCHITECTURE.md:54-58`, Meta-prompting critical path).
- The existing FileAgent canonicalizes its root and constructs exactly two mutation roots, `Incoming` and `Sorted` (`agents/file_agent.py:82-93`, `FileAgent.__init__`). `_sandbox_path` resolves each path with `realpath`/`abspath` and accepts it only when `commonpath`/`normcase` matches one of those roots (`agents/file_agent.py:144-160`, `FileAgent._sandbox_path`).
- The current C3/C4 acceptance language requires a real-file patch that does not destroy unrelated code, clean malformed-patch rejection, a bounded self-healing loop, sandbox containment, and per-iteration logging (`PLAN.md:309-320`, C3 and C4 backlog items).

---

## 2. Threat model and new surfaces

### 2.1 Central fact

**C3 is the first mutation surface outside Incoming/Sorted.** Existing file operations move, rename, delete to recycle bin, and create folders under the two existing roots; their dispatch is limited to the declared tool set (`agents/file_agent.py:123-142`, `FileAgent.system_prompt`; `agents/file_agent.py:1260-1344`, `FileAgent._execute_tool_plan`). C3 would instead alter the **content** of source files.

Unlike a filename or category, arbitrary code content is the intended payload and therefore cannot be made safe by “sanitizing” it. The patch may legitimately contain hostile-looking strings, imports, commands, or other source text. Safety must instead come from:

- boundary containment;
- exact-diff approval;
- bounded blast radius;
- durable journaling and recovery; and
- **non-execution**.

No current source-editing component exists. Syntax is routed without tools (`agents/plan_agent.py:250-263`, `PlanAgent.build_plan`), while the code index only parses Python with `ast.parse` and derives identifiers (`agents/code_index_agent.py:211-264`, `CodeIndexAgent._analyze_source`). Neither is a write surface.

### 2.2 Adversaries and failure sources

The relevant adversary is not only a malicious model response. It also includes a malformed or confused provider response, a stale artifact, a hostile path in a patch, a compromised dependency, a second STEWARD process, an unrelated editor or build tool, and local filesystem faults.

| Threat | Consequence if uncontrolled | Required C3 control |
|---|---|---|
| Absolute or traversal path | Write outside the authorized workspace | Model supplies only normalized workspace-relative paths; app joins them to the selected root; canonical containment is rechecked |
| Symlink/junction swap | Write escapes the selected root | Reject reparse-point components; canonicalize and recheck immediately before publication; retain residual-race disclosure |
| Stale source | Patch applies to different code than reviewed | Bind approval to raw-byte SHA-256 of every source file; recheck each hash before its replacement |
| Malformed patch | Partial or ambiguous application | Validate the entire artifact and all edits before any source mutation; stage all outputs first |
| Oversized patch | Resource exhaustion or broad damage | Fixed files/edit/byte/total-size caps |
| Hostile code content | Immediate compromise only if run | C3 never imports, executes, lints, or runs the result |
| Secret/denied path exposure or mutation | Credential/config damage | Independent write denylist and path-component checks |
| Concurrent STEWARD process | Lost history or competing undo/redo | Reuse the persistent cross-process sidecar lock around intent, mutation, and completion |
| Concurrent external process | Reviewed bytes differ from replaced bytes | Hash/identity recheck before replacement; atomic local replacement; disclose residual non-cooperating TOCTOU window |
| Journal failure after mutation | Filesystem and history disagree | Intent first, completion afterward, immutable pre/post-image evidence, and `uncertain` state |
| Disk full/read-only target | Partial multi-file patch | Stage and preflight every output before commit; per-file commit progress; rollback or `uncertain` recovery |
| BOM/CRLF/mixed newline | Byte churn or broken encoding | Raw-byte pipeline; preserve BOM and existing CRLF; reject unsupported/mixed encodings in v1 |

### 2.3 Security properties

A future C3 must establish these properties:

1. **Authorized-root only:** every target is an existing regular file under the one root the user selected for this operation.
2. **No path authority from the model:** the model never supplies an absolute path, drive, UNC path, or root override.
3. **Exact review:** the bytes shown in the approved diff are the bytes applied.
4. **Bounded mutation:** all patch and per-edit caps are fixed and enforced before mutation.
5. **Non-execution:** no path from the patch reaches an import, evaluator, subprocess, test, or linter.
6. **Truthful recovery:** an unknown filesystem outcome is `uncertain`, not reported as success, and blocks blind undo/redo.
7. **Existing sandbox isolation:** Incoming/Sorted rules and behavior remain unchanged.

---

## 3. Mutation-boundary decision

### 3.1 Options evaluated

#### Option A — explicit code-workspace mutation root (recommended, re-scoped)

Add a **new, explicit user-selected code workspace** mutation root, parallel to and separate from Incoming/Sorted. It has its own admission policy, denylist, realpath containment, approval artifact, and journal operation kind. The model cannot select it.

**Advantages**

- It preserves C3’s stated goal of applying a patch to a real file (`PLAN.md:309-317`, C3 backlog item).
- It gives code mutation a boundary that can be reviewed independently rather than weakening the file-organizer sandbox.
- It can reuse the journal lock and durable-history infrastructure without changing move/rename semantics.
- It permits exact-byte approval and content-specific recovery without pretending the existing move primitive replaces file contents.

**Costs and required narrowing**

- It creates a real source-mutation capability and therefore needs a dedicated implementation/safety batch.
- Multi-file application cannot be made atomic across separate files with the current filesystem primitives.
- A non-cooperating external editor can race after the final check; this cannot be completely eliminated with the current portable Python APIs.

#### Option B — patch-to-staging only

Write patched copies to an app-owned staging area and require the user to apply them manually.

**Advantages:** zero new source-mutation surface; easy inspection; no target overwrite.
**Costs:** it does not meet PLAN’s C3 acceptance target of applying a patch to a real file (`PLAN.md:309-317`). It is better described as an export/diff feature than C3. It also does not remove the need for safe path naming, exact diffs, secret-path denial, backup retention, or conflict handling when the user later applies the result.

#### Option C — defer C3 entirely

**Advantages:** no new mutation risk.
**Costs:** the central C3 design remains unresolved, and the roadmap remains blocked behind an untested safety model. This review can provide enough specificity to avoid an unreviewed implementation later.

### 3.2 Decision

**Recommend Option A, explicitly re-scoped, and keep C3 in BACKLOG until a separate implementation batch satisfies every acceptance criterion in Section 13.** Do not widen or reuse the existing Incoming/Sorted sandbox.

Option B is rejected as the primary C3 implementation because it does not satisfy the current C3 acceptance line. Option C is unnecessary after this review establishes a bounded design, provided the implementation remains backlogged and no capability is implied by the roadmap.

### 3.3 Exact recommended boundary

#### Root selection and lifetime

1. The user selects one directory through an explicit native directory picker or equivalent UI control. The app canonicalizes it with `abspath` + `realpath`; the model has no role in root selection.
2. The canonical root must not be a filesystem/Windows drive root, a user home root, the app-data directory, or the app-data `STEWARD` directory.
3. The canonical root must be disjoint from Incoming and Sorted: reject equality, ancestry in either direction, and overlap. This preserves a separate parallel boundary.
4. The root is bound to the patch artifact by a stable workspace fingerprint derived from its canonical path and filesystem identity. A different root invalidates approval.
5. The root is valid only for the preview/approval/apply transaction. A later patch requires a new explicit selection; the app must not silently reuse a remembered writable root.

The existing Incoming/Sorted roots remain exactly as constructed in `FileAgent.__init__` and enforced by `_sandbox_path` (`agents/file_agent.py:89-93`, `agents/file_agent.py:144-160`). C3 must not call `_sandbox_path` for code targets and must not add the code root to `allowed_roots`.

#### Target admission

For every relative target path, the future app must:

1. require a non-empty POSIX-style relative path;
2. reject absolute paths, drive-qualified paths, UNC paths, `.`/`..` components, NUL, reserved names, and trailing spaces/dots;
3. join it to the canonical selected root without allowing the joined value to escape;
4. resolve `abspath` + `realpath`, then require `commonpath` + `normcase` containment;
5. reject a symlink or Windows junction/reparse point in **any** path component, including the target itself;
6. require the final target to exist and be a regular file;
7. admit only `.py` files in v1;
8. reject any path matching the write denylist below; and
9. revalidate all of the above immediately before replacing that file.

This parallels the code-index read boundary, which canonicalizes an explicit root and uses `realpath`/`abspath`/`commonpath`/`normcase` containment (`agents/code_index_agent.py:131-159`, `CodeIndexAgent._normalize_root` and `_contained_by`). The read boundary also recognizes symlinks and Windows junctions (`agents/code_index_agent.py:176-186`, `_is_escape` and `_is_link_or_junction`) and refuses out-of-root link targets (`agents/code_index_agent.py:329-360`, `_candidate_files`). C3’s stricter rule refuses link components even when they point inside the root because a link-swap race makes them unsafe for writes.

#### C3 write denylist (independent of the read denylist)

Reject any path component or filename matching these case-insensitive rules:

- directory components: `.git`, `.hg`, `.svn`, `__pycache__`, `venv`, `.venv`, `node_modules`, `rag_index`, `media`, `.tox`, `.nox`, `.pytest_cache`, `.mypy_cache`;
- filenames: `.env`, any `.env.*`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `*.db`, `secret.key`, `steward_operations.json`, `credentials.json`, `.npmrc`, `.pypirc`.

The baseline for `.env*`, `*.key`, `*.db`, `secret.key`, and `steward_operations.json` is the current code-index read denylist (`agents/code_index_agent.py:161-174`, `_is_denied_relative_path`). The additional names are conservative write exclusions proposed here, not claims about current behavior. The selected root’s own basename is subject to the directory denylist, mirroring the existing read-side root check (`agents/code_index_agent.py:139-146`, `_is_denied_root`).

#### Admission and mutation limits

- Existing regular `.py` files only.
- No new-file creation, file deletion, rename, move, chmod, or metadata-only mutation.
- No target outside the selected root, including through links.
- No execution, import, lint, or test of any target.
- No C3 target may be `steward.db`, `secret.key`, the operation log, or a plan/patch artifact.

These restrictions make C3 a content-edit capability only, not a general file-edit API.

---

## 4. Patch schema

### 4.1 Required strict JSON shape

The future patch artifact should be strict JSON with exactly these top-level keys:

- `schema_version`: exact integer `1`;
- `patch_id`: app-assigned UUID, not model-selected;
- `plan_id`: the reviewed C2 plan UUID;
- `workspace_fingerprint`: app-derived fingerprint of the selected root;
- `files`: ordered array of file edit objects;
- `created_utc`: bounded ISO-8601 timestamp.

Each file object must contain exactly:

- `relative_path`: normalized workspace-relative POSIX path;
- `source_sha256`: 64 lowercase hexadecimal characters over the complete original raw bytes;
- `source_bytes`: positive integer equal to the original byte length;
- `encoding`: exact string `utf-8`;
- `bom`: boolean;
- `newline`: exact string `lf` or `crlf`;
- `edits`: ordered, non-empty array.

Each edit object must contain exactly:

- `op`: one of the operations in Section 4.3;
- `anchor`: an AST anchor object validated against the source tree;
- `replacement`: UTF-8 source text for the operation, with the same declared newline policy;
- `expected_sha256`: 64 lowercase hexadecimal characters over the exact pre-image span the edit addresses.

No unknown keys, duplicate JSON keys, alternate path keys, command keys, executable keys, or free-form absolute paths are allowed. Validation follows the strict-key precedent in `validate_blueprint`, which requires exact key sets and bounded typed values (`agents/plan_agent.py:81-147`, `validate_blueprint`).

### 4.2 Deterministic bounds

Before any source mutation, reject a patch exceeding any cap in Section 8. Bounds apply to decoded JSON structure and encoded artifact bytes; both must be checked so neither representation bypasses a limit.

### 4.3 Edit-operation vocabulary

Keep v1 deliberately small:

1. `replace_node`: replace the exact source span of one admitted AST node;
2. `insert_before`: insert source text immediately before one admitted AST node;
3. `insert_after`: insert source text immediately after one admitted AST node;
4. `delete_node`: delete one admitted AST node’s exact span.

The anchor must use a stable structural identity, not a model-provided absolute path or line number. A proposed v1 anchor is `{node_kind, qualified_name, occurrence}` plus `source_start`/`source_end` character offsets as a consistency check. `qualified_name` is a dotted definition path such as `Module.Class.function`; `occurrence` disambiguates repeated definitions. The app resolves the anchor from the parsed tree, verifies the exact span hash, and rejects an ambiguous or missing anchor. An edit may not target module docstrings, import statements, or expressions in v1; that keeps the grammar small and reduces malformed-output risk. Insertions are parsed in the target context before staging.

### 4.4 Target binding and model path authority

A model response may supply only the relative path and structural edit intent. The app resolves the path beneath the already selected root; it must not accept or resolve a model-supplied absolute path. This follows the C2 precedent that targets are informational text and never reach FileAgent (`agents/plan_agent.py:150-160`, architect/builder prompts; `PLAN.md:88-94`, C2 implemented record).

Binding is twofold: source hash binds the patch to the reviewed original bytes, while patch ID + artifact hash binds approval to this exact patch. Reapplying the same patch to changed bytes must fail rather than merge or regenerate.

### 4.5 Malformed-patch rejection

A patch is rejected before the first target mutation if JSON, keys, types, caps, paths, hashes, encoding metadata, anchors, overlaps, context parses, or generated bytes are invalid. Edits within a file must not overlap and must be applied in source order to a copy. All generated files must parse as Python and satisfy the same size cap before any publication begins. “No partial application” means malformed input causes zero target-file changes; staging artifacts may be created and then removed, but no admitted source file is touched.

---

## 5. Formatting and comment preservation

### 5.1 Candidate approaches

#### `ast.unparse` — reject

`ast.unparse` reconstructs syntax from the AST. It does not preserve original comments, blank-line layout, quote choices, spacing, or most formatting. It also does not provide an exact byte-preserving unrelated-region guarantee. This is acceptable for analysis but fails the “without destroying unrelated code” requirement when used as the patch writer. The existing indexer uses `ast.parse` only to derive structure (`agents/code_index_agent.py:211-264`, `_analyze_source`); it does not demonstrate safe source regeneration.

#### LibCST — capable but not recommended for v1

LibCST can preserve comments and much concrete formatting and provides a CST representation suitable for structural edits. However, it is a third-party dependency, has its own version/behavior surface, and still requires careful byte-level BOM/newline handling and proof that untouched regions are unchanged. Adding it is justified only if a bounded token/segment approach cannot meet the acceptance criteria. It is not justified merely to avoid writing a small, strict patch engine.

#### parso — capable but not recommended for v1

parso preserves formatting and comments through a concrete syntax tree and has useful error recovery. It is also a new third-party dependency. Its error-recovery behavior is undesirable at a mutation boundary unless every recovered tree is proved equivalent to strict Python parsing; otherwise a malformed patch could be “successfully” applied in a form the stdlib parser rejects. It offers no advantage over a stdlib-token approach for the small v1 operation vocabulary.

#### Token/segment splicing — recommended

Use stdlib `tokenize`/source offsets to splice only exact admitted source spans, while using `ast` to resolve and validate structural anchors. Keep original source as raw bytes. Decode according to detected UTF-8/BOM policy, map token and AST spans to byte offsets, and replace only the selected spans. This avoids whole-file reformatting and makes unrelated-byte preservation provable.

### 5.2 Dependency justification

The recommendation is **stdlib `ast` + `tokenize`/offset splicing, with no new dependency**. This follows the project precedent that rejected third-party locking packages as unnecessary (`PLAN.md:143-154`, FS-S5 design and dependency rationale). A parser dependency is justified only if v1 cannot satisfy comment/format preservation and strict malformed-input rejection. It should not be added speculatively.

### 5.3 BOM, CRLF, and byte preservation

- Read target bytes without newline translation. Detect UTF-8 BOM separately; preserve the BOM bytes exactly.
- Require UTF-8. Reject UTF-16, other encodings, undecodable bytes, and mixed newline conventions in v1 rather than guessing.
- If the original is LF, edited inserted text is normalized to LF; if CRLF, it is normalized to CRLF. The original file’s newline mode is bound into the artifact and diff.
- Outside edited byte spans, output bytes must be exactly equal to input bytes. Inside an edited span, only the approved replacement bytes differ.
- Preserve final-newline presence/absence unless the edit explicitly changes it.

The current code index reads raw bytes and decodes with `utf-8-sig`, using replacement only for read-only analysis (`agents/code_index_agent.py:362-378`, `_read_bounded`). That behavior is a useful encoding-detection precedent, but C3 must be stricter: unsupported or malformed bytes are refusal, not lossy replacement.

### 5.4 Proof of “unrelated code unchanged”

The future implementation must compute and persist, for each file:

- original SHA-256, output SHA-256, and byte length;
- the sorted exact byte ranges of every edit;
- the concatenated SHA-256 of every original byte range outside those ranges;
- the same value computed from output bytes; and
- the exact unified diff artifact.

Equality of the outside-range digest, plus exact diff review, proves unrelated bytes were unchanged. A semantic AST comparison is useful as an additional check, but it is **not** the proof because AST equivalence cannot prove formatting/comment preservation. The current indexer hashes raw bytes for changed-file replacement (`agents/code_index_agent.py:362-378`, `_read_bounded`), which is a precedent for content identity, not a source-edit guarantee.

---

## 6. Approval boundary

### 6.1 Plug into C2 without weakening it

C3 must consume a C2 plan that has already passed the existing review gate. The current `PlanAgent` stores a pending artifact ID, approves exactly that pending ID, and consumes it once in `build_plan`; unknown/stale/superseded/replayed IDs share one refusal (`agents/plan_agent.py:163-176`, `PlanAgent.__init__`; `agents/plan_agent.py:213-245`, `approve_plan`, `decline_plan`, `invalidate_pending_plan`, and `build_plan`). The persisted artifact is app-assigned UUID JSON under the app’s `plans` directory, written atomically and validated again on load (`agents/plan_agent.py:328-386`, `_artifact_path`, `_persist_artifact`, `_load_artifact`; `core/database.py:20-22`, `APP_DATA_DIR`).

For C3, extend this lifecycle with a distinct, immutable **patch artifact** and a distinct single-use approval. Do not reuse the consumed C2 builder approval to authorize mutation. The patch artifact must reference the exact C2 `plan_id` and store the complete validated patch, approved source hashes, output hashes, exact diff bytes, and workspace fingerprint.

### 6.2 Immutable artifact and exact preview

The app, not the model, assigns the patch UUID and persists the artifact once under an app-owned directory. Publication must use write-once semantics; it may use the existing no-overwrite pattern for regular files (`agent/tools.py:80-116`, `_publish_without_overwrite`) or an equally strict app-owned mechanism. The exact diff is generated from original raw bytes to staged output raw bytes and is included in the immutable artifact. The preview shown to the user must render those exact diff bytes, not a regenerated model diff.

The approval ID is bound to:

- patch artifact UUID and artifact SHA-256;
- C2 plan UUID;
- workspace fingerprint;
- ordered list of target relative paths;
- original and output file hashes; and
- the conversation/session epoch.

### 6.3 Refusal contract

Approve/decline/apply must share one refusal contract for:

- unknown ID;
- stale or superseded patch;
- already consumed/replayed approval;
- declined or cleared pending patch;
- changed conversation epoch;
- changed workspace fingerprint;
- changed source hash;
- changed patch artifact hash; and
- any preview/apply capability cancellation.

This mirrors the C2 single-use refusal semantics (`agents/plan_agent.py:213-245`, approval lifecycle) and the immutable-plan execution behavior in FileAgent, where the exact pending plan is claimed under a lock and executed once (`agents/file_agent.py:1348-1374`, `get_pending_plan_id`, `execute_pending_plan`, `discard_pending_plan`).

### 6.4 Epoch guards

The GUI must carry the request-local conversation epoch into patch preview, approve/decline callbacks, and apply. Any callback from an earlier epoch is ignored/refused. The patch artifact’s approved epoch must equal the epoch at apply. Clearing chat invalidates the pending patch and approval exactly as C2’s `invalidate_pending_plan` clears its pending/approved IDs (`agents/plan_agent.py:227-231`, `PlanAgent.invalidate_pending_plan`).

The approved diff must be the exact bytes applied. Enforce this by applying a staged file whose SHA-256 equals the artifact’s approved output SHA-256, then verifying the on-disk result equals that hash. If the staged file, artifact, preview, or target differs, refuse rather than re-rendering or reapplying.

---

## 7. Journal and recovery

### 7.1 Reuse the durable journal and cross-process lock

Reuse `steward_operations.json` and `operation_journal_lock`. The journal path defaults under app data (`agents/file_agent.py:75-80`, `FileAgent.DEFAULT_OPERATION_LOG_PATH` and `OPERATION_LOG_PATH`). The sidecar is stable, never removed, and uses an OS-managed exclusive lock with a bounded timeout (`agent/journal_lock.py:1-5`, module contract; `agent/journal_lock.py:93-191`, `operation_journal_lock`). The existing mutation path holds this lock across refresh, intent, filesystem action, and completion (`agents/file_agent.py:470-490`, `_execute_mutation`; `agents/file_agent.py:492-579`, `_execute_mutation_locked`).

For a content edit, the journal entry should be a distinct operation kind, for example `content_edit`, with metadata for patch ID, workspace fingerprint, relative path, pre-image hash, post-image hash, pre-image backup reference, exact byte length, and per-file progress. The journal itself must not contain source content.

### 7.2 Intent/completion and exact backups

Sequence under the cross-process lock:

1. Validate the approved artifact and all target hashes.
2. Write a durable `intent` entry with target identity and expected hashes **before** target mutation.
3. Copy the exact pre-image to an app-owned backup location, flush and `fsync` it, and record its hash/reference in the intent before replacement.
4. Stage the approved output in the target directory, flush and `fsync`, and verify its hash.
5. Recheck source hash/path admission immediately before replacement.
6. Replace the target using a same-directory atomic replacement that is explicitly allowed to overwrite **only this admitted target**. This is a new primitive; it must not reuse the move/rename no-overwrite semantics.
7. Write durable completion with post-image hash and backup reference.

The existing write-ahead pattern records intent before disk changes and completion afterward (`agents/file_agent.py:412-446`, `_begin_mutation` and `_complete_mutation`). Interrupted intents/transitions reload as `uncertain` (`agents/file_agent.py:209-249`, `_load_operation_log`).

### 7.3 Backups and undo

The current no-overwrite publication primitive copies a source to a destination and removes the source afterward (`agent/tools.py:80-136`, `_publish_without_overwrite` and `_move_without_overwrite`). It is move/rename oriented and **does not directly cover content replacement**. Therefore C3 needs explicit content pre-image and post-image evidence; pretending the existing primitive provides content undo is incorrect.

Backups live under app-owned `%APPDATA%\STEWARD\c3_backups` (the app-data root is `core/database.py:20-22`, `APP_DATA_DIR`), never inside the selected workspace. Use an app-assigned UUID directory with restrictive permissions where supported. Store:

- exact original bytes;
- exact applied bytes;
- SHA-256 for both;
- target relative path and workspace fingerprint;
- patch/operation IDs;
- creation time; and
- original file identity (device/inode where meaningful).

Retention: keep backups for the newest 20 committed content-edit operations and for any operation that is undoable or uncertain; prune older committed, undone operations only after their journal entries no longer reference them. Uncertain or undoable backups are never pruned automatically. This mirrors the bounded “keep newest 20” precedent for plan artifacts (`agents/plan_agent.py:27`, `MAX_RETAINED_PLANS`; `agents/plan_agent.py:388-410`, `_prune_artifacts`) while preserving recovery evidence.

### 7.4 Content-edit undo/redo

Undo verifies that the target still equals the recorded post-image hash, then atomically restores the exact pre-image. If the target differs, undo refuses rather than overwriting an unknown external edit. Redo restores the exact post-image only when the target equals the recorded pre-image hash; otherwise it refuses.

Undo/redo claims must use the same cross-process lock and write-ahead transition used by existing history transitions (`agents/file_agent.py:581-619`, `_begin_transition`, `_complete_transition`, `_mark_transition_uncertain`, `_mark_transition_failed`; `agents/file_agent.py:632-755`, `undo_last` and `redo_last`). The current undo/redo refuses when history contains an uncertain transition (`agents/file_agent.py:646-654` and `agents/file_agent.py:757-764`). C3 must preserve this rule: an `uncertain` content edit blocks blind undo/redo across the content-edit history until explicit manual reconciliation resolves it.

---

## 8. Blast-radius bounds

The following are proposed hard caps for the first implementation:

| Bound | v1 cap |
|---|---:|
| Files per patch | 5 |
| Edits per file | 20 |
| Total edits per patch | 50 |
| Bytes per edit (replacement plus anchor metadata) | 16 KiB |
| Total patch artifact bytes | 256 KiB |
| Original bytes per target file | 1 MiB |
| Output bytes per target file | 1 MiB |
| Total original + output bytes across patch | 2 MiB |

Additional rules:

- **No new-file creation in v1.** This avoids directory creation, path admission, publication, and undo semantics beyond content replacement.
- **No file deletion in v1.** This avoids ambiguity between deleting source content and deleting a filesystem object.
- No rename, move, chmod, symlink creation, or metadata mutation.
- No execution, import, lint, test, build, or package installation—ever—in C3.
- No patch may span more than one workspace root.

The caps are intentionally small because arbitrary code content is not sanitizable. Future expansion requires a new review and explicit PLAN amendment, not silent relaxation.

---

## 9. Failure modes and rollback

| Failure | Required recovery contract |
|---|---|
| Malformed JSON/schema/anchor/context | Reject before target mutation; zero admitted source files change; remove staging artifacts. |
| Path outside root, denied path, link/junction target | Refuse before opening the target for write; record no mutation intent. |
| Source changed between preview and apply | Recheck raw-byte hash and identity immediately before replacement; refuse the whole patch if any file changed. No regeneration or forced apply. |
| Source changes between per-file checks in a multi-file patch | Stop before the next file. Preserve journal evidence; mark the patch partial/uncertain; attempt verified rollback only for files whose current hash still equals the applied post-image. If any file cannot be proven, mark `uncertain` and block blind undo/redo. |
| Journal cannot record intent | Do not mutate any target; return failure. This matches the existing “operation was not started” behavior (`agents/file_agent.py:504-510`, `_execute_mutation_locked`). |
| Backup cannot be written/verified | Do not replace the target. |
| Staging write fails or disk is full | Do not replace the target; clean only verified-owned staging files. |
| Target is read-only or permission denied | Preflight writability where possible, then treat replacement failure before mutation as `failed`. If replacement may have occurred, verify the target hash and mark `uncertain` when outcome is not provable. |
| Atomic replacement fails | Inspect the target’s raw hash and identity. If unchanged, record `failed`; if it equals the intended post-image, record `committed`; otherwise record `uncertain`. Never claim a failed mutation was clean. |
| Completion journal write fails after replacement | Mark the operation `uncertain`, retain backup, and block blind undo/redo. This is the existing truthfulness pattern (`agents/file_agent.py:560-569`, `_execute_mutation_locked`). |
| Process dies after intent, before/after replacement | On reload, an interrupted intent becomes `uncertain` (`agents/file_agent.py:223-234`, `_load_operation_log`); reconcile by comparing target hash with pre/post-image evidence, never by blind retry. |
| Encoding/BOM/newline violation | Refuse before target mutation; no lossy conversion. |
| External editor writes after C3 replacement | C3’s operation is committed for its applied bytes; a later undo/redo refuses if the current target no longer matches the expected post/pre-image hash. |

### 9.1 Multi-file atomicity

A patch spanning several files cannot be one atomic filesystem transaction. The design therefore uses **all-or-refuse before commit**, then per-file atomic replacement with durable progress. If one file fails after another succeeded, the patch is partial and must be rolled back where provable. Exact per-file progress and both image hashes are mandatory in the journal.

### 9.2 Rollback

Rollback is hash-guarded, not time-based: restore only when the current target still equals the image that operation installed. Never overwrite an unknown external edit. If any target’s current hash is unknown, stop and report manual reconciliation. The journal records `failed` only after verified restoration; otherwise `uncertain`.

---

## 10. UI impact

The future UI must make the mutation boundary visible and reviewable:

1. **Workspace selection:** an explicit “Select code workspace” control; display the canonical selected root and the fact that it is separate from Incoming/Sorted. No model-provided path field.
2. **Patch preview:** show target relative paths, exact unified diff, old/new hashes, edit counts, and any bounds/truncation notice. The diff is the immutable artifact’s bytes.
3. **Approve/decline:** explicit buttons bound to the pending patch UUID and current epoch. Decline invalidates the pending approval without touching the workspace.
4. **Live Feed:** distinct entries for preview ready, approved, applying per file, completed, refused, partial, failed, uncertain, undone, and redone. Do not imply lint/test/execution occurred.
5. **Cancellation:** cancel before apply invalidates the pending patch/approval. Once target mutation begins, cancellation is not a blind abort: it stops at a safe boundary, records the exact per-file state, and offers recovery. Cancellation cannot bypass journaling.
6. **Epoch guards:** stale preview/approval/apply callbacks are ignored or refused; clear-chat invalidates pending patch state.
7. **Undo/redo:** expose content-edit undo/redo with the current target-hash guard and the uncertain-state block. The existing GUI already has epoch-guarded activity and file approval surfaces (`ARCHITECTURE.md:31-35`, module roles), but this review does not assert a current C3 UI.

No UI text may claim that patched code was run, tested, linted, imported, or verified at runtime. The only success claim is “approved bytes applied to admitted file(s)” with the recorded hashes.

---

## 11. Future implementation test plan

This section is a plan for a future implementation batch. **No tests are added in C3-R.**

### 11.1 RED → GREEN and mutation proofs

Each safety test begins RED against the unsafe/unimplemented behavior, then GREEN after the fix. Safety guards also receive mutation proof: remove or weaken the guard, show the relevant test becomes RED, restore it, and show GREEN. The project’s proof standard is RED → fix → GREEN with mutation proof for safety items (`ARCHITECTURE.md:197-207`, Tests and proof standard).

### 11.2 Patch-schema and adversarial tests

- unknown top-level/file/edit keys; wrong types; duplicate keys; absolute/drive/UNC/traversal paths; NUL/reserved names;
- bad source hash, bad anchor span hash, ambiguous anchor, missing anchor, overlapping edits;
- insertion that does not parse in context; output that does not parse; malformed UTF-8/BOM/newline;
- every bound at limit and limit+1; total edits and aggregate bytes;
- model response containing a tool call or executable command is not accepted as patch authority;
- malformed patch yields zero target changes and no successful journal entry.

### 11.3 Mutation proofs

- a patch applies to a real admitted `.py` file and the result parses;
- patch output differs from input only in approved byte ranges;
- comments and formatting outside edited spans remain byte-identical;
- source hash change between preview and apply refuses and does not mutate;
- removal of root containment, denylist, hash check, approval consumption, or non-execution guard each turns a safety test RED.

### 11.4 Formatting-preservation proof

Fixture files must cover comments, blank lines, unusual spacing/quoting, trailing whitespace, no final newline, UTF-8 BOM, LF, and CRLF. For each, assert:

- BOM bytes and newline mode are preserved;
- bytes outside declared edit ranges are identical;
- comments outside the edited node remain identical;
- output parses;
- exact approved diff bytes equal the on-disk delta.

### 11.5 Hostile-path tests

- target outside root via `..`, absolute path, alternate drive, UNC, case variation, common-prefix sibling directory;
- symlink/junction file, directory component, and race substitution;
- denied `.env`, `.env.*`, `*.key`, `*.pem`, `*.db`, `secret.key`, `steward_operations.json`, dependency/cache directories;
- selected root equal to/containing/contained by Incoming or Sorted is refused;
- app-data and database/key paths are refused.

### 11.6 Concurrency, journal, and recovery tests

- two real processes attempt patches to the same target: one wins; the other rehashes and refuses;
- separate processes cannot both claim undo or redo;
- lock timeout fails closed before target mutation;
- process death after intent and after replacement reloads as `uncertain`;
- completion journal failure after replacement records `uncertain` and blocks blind undo/redo;
- backup write/hash failure prevents replacement;
- disk-full staging failure prevents replacement;
- per-file partial failure rolls back provably applied files and preserves uncertain state where rollback cannot be proven;
- undo/redo restores exact bytes and refuses after an external edit.

### 11.7 Non-execution proof

Instrument subprocess, import, test, lint, and execution APIs to fail if invoked during patch generation, preview, approval, apply, undo, or redo. Assert C3 changes source bytes only through the dedicated content-edit path.

---

## 12. Open questions, residual risks, and recommendation

### 12.1 Open questions for the future implementation batch

1. Should v1 permit `delete_node` at all? It is semantically useful but makes “delete code” a first-class mutation; a safer first cut may allow only replacement and insertion.
2. How should AST anchors address overloaded/nested definitions? The v1 `qualified_name` + occurrence scheme is a proposal, not proven by this review.
3. Should the patch artifact live under the existing app-owned `plans` directory or a sibling `patches` directory? Either is viable; it must remain outside user workspaces and use write-once persistence.
4. What is the exact portable strategy for atomic replacement while preserving permissions and reporting every outcome on Windows and POSIX? The current move publication primitive does not answer content replacement (`agent/tools.py:80-136`, `_publish_without_overwrite` and `_move_without_overwrite`).
5. How should file identity be captured portably when inode/device are weak or unavailable on Windows?
6. Should the first implementation permit multiple files, or restrict v1 to one file to eliminate cross-file partial application? This review permits up to five only with explicit partial-recovery requirements; one file is the safer default if implementation complexity grows.
7. What exact user-visible recovery flow resolves an `uncertain` content edit without an unreviewed “force overwrite” action?

### 12.2 Residual risks

- **External-process TOCTOU:** the cross-process sidecar protects cooperating STEWARD processes, not editors or arbitrary tools. Hash/identity rechecks narrow the race; they cannot prove no external write occurs between final check and replacement with the current portable APIs.
- **Multi-file partial state:** per-file atomic replacement is not a transaction across files. Hash-guarded rollback reduces but does not erase this risk.
- **Parser gaps:** stdlib `ast` covers Python syntax accepted by the running interpreter, but token offsets, encodings, BOMs, CRLF, and future syntax versions require careful version-specific tests.
- **Comments attached to an edited node:** preserving comments outside the edited span is provable; comments inside a replaced/deleted node cannot be preserved unless the edit vocabulary explicitly carries them.
- **Permission/ACL and antivirus interference:** replacement can fail or have delayed effects even after preflight.
- **Backup confidentiality:** backups contain source code. They remain app-owned and should use restrictive permissions where supported, but they are another copy of sensitive source.
- **Dependency compromise:** no new parser dependency is recommended for v1, but the stdlib parser still determines accepted syntax.

### 12.3 Recommendation

**RE-SCOPE and proceed to a future implementation batch under the bounded design in this document.** Specifically:

- adopt Option A: a new explicit code-workspace mutation root, parallel to and separate from Incoming/Sorted;
- keep C3 and C4 in BACKLOG now;
- use stdlib AST anchoring plus byte-preserving token/segment splicing, with no new dependency in v1;
- require an immutable patch artifact, exact diff, distinct single-use ID/epoch-bound approval, and exact approved bytes;
- reuse the durable journal/cross-process lock but add explicit content pre/post-image backup and undo/redo semantics;
- disallow file creation/deletion and all execution in v1; and
- require the future test plan and acceptance criteria below before merge.

This is neither a feature approval nor permission to implement. It is a safety-reviewed scope for the next batch. If the future implementation cannot prove byte preservation, exact approved bytes, or hash-guarded recovery, the correct outcome is to stop and re-review rather than weaken the boundary.

---

## 13. Acceptance criteria for the eventual C3 implementation batch

These criteria derive from PLAN’s C3 acceptance line (`PLAN.md:309-317`) and this review. All are required.

1. **Real-file application:** an approved patch applies to an admitted real `.py` file and the result parses.
2. **Unrelated code preserved:** bytes outside declared edit ranges are identical; comments and formatting outside edited spans remain byte-identical.
3. **Malformed rejection:** malformed JSON/schema/path/hash/anchor/context is rejected cleanly with zero target-file changes.
4. **Separate boundary:** mutation occurs only under the explicitly selected code workspace; the Incoming/Sorted sandbox is unchanged and is neither reused nor widened.
5. **Path admission:** model output cannot select an absolute path; traversal, common-prefix escape, denied/secret paths, symlinks, and junctions are refused before write.
6. **Exact approval:** the immutable patch artifact, displayed diff, approval ID, source hash, output hash, workspace fingerprint, and epoch are bound; the applied bytes equal the approved bytes.
7. **Single use and stale refusal:** unknown, stale, superseded, replayed, declined, cleared, and wrong-epoch IDs use one refusal contract and mutate nothing.
8. **Bounded blast radius:** the Section 8 caps are enforced at and above their boundaries; v1 creates and deletes no files.
9. **Non-execution:** C3 never imports, executes, lints, tests, builds, or starts a subprocess on patched content.
10. **Truthful journal:** intent precedes mutation, completion follows it, per-file progress is durable, and journal failure produces truthful `failed`/`uncertain` state.
11. **Content undo/redo:** exact pre/post-image backups enable undo and redo; current-hash guards refuse to overwrite an external edit; `uncertain` blocks blind undo/redo.
12. **Recovery:** partial multi-file application rolls back only where provable and otherwise remains explicit `uncertain`; disk-full, read-only, encoding, backup, staging, and journal failures have deterministic contracts.
13. **Formatting/encoding:** UTF-8 BOM and LF/CRLF are preserved byte-for-byte outside edited regions; unsupported encoding and mixed newline modes are refused.
14. **Cross-process safety:** the persistent sidecar lock serializes cooperating STEWARD processes, fails closed on timeout, and prevents competing undo/redo claims.
15. **UI honesty:** the UI shows the exact diff and workspace boundary, supports approve/decline/cancel, reports Live Feed states and epoch guards, and never claims runtime verification.
16. **Proof standard:** RED → GREEN, mutation proofs for each safety guard, separate-process contention tests, hostile-path tests, formatting proofs, content undo/redo tests, and the full existing suite remain green.

---

## Evidence index and evidence gaps

- **Current approval artifact and gate:** `agents/plan_agent.py:81-147`, `validate_blueprint`; `agents/plan_agent.py:163-267`, `PlanAgent`; `agents/plan_agent.py:328-410`, artifact path/persistence/loading/pruning.
- **Current FileAgent sandbox:** `agents/file_agent.py:82-202`, `FileAgent.__init__`, `_sandbox_path`, `_validate_mutation`.
- **Current immutable file plan execution:** `agents/file_agent.py:986-1126`, `FileAgent.run`; `agents/file_agent.py:1129-1381`, parse/preview/preflight/execute/discard.
- **Current journal lifecycle:** `agents/file_agent.py:209-620`, load/merge/save/intent/complete/mutation execution/transition state.
- **Current undo/redo:** `agents/file_agent.py:632-839`, `undo_last`, `_undo_last_locked`, `redo_last`, `_redo_last_locked`.
- **Current no-overwrite publication:** `agent/tools.py:30-136`, outcome error, rollback, `_publish_without_overwrite`, `_move_without_overwrite`.
- **Current cross-process lock:** `agent/journal_lock.py:1-191`.
- **Current read-side code boundary:** `agents/code_index_agent.py:22-190`, constants/root/denylist/containment/link handling; `agents/code_index_agent.py:211-264`, AST analysis; `agents/code_index_agent.py:329-378`, traversal and bounded raw-byte read.
- **App-data location:** `core/database.py:20-22`.
- **Plan/roadmap intent:** `PLAN.md:295-320`, Phase C gate and C3/C4; `PLAN.md:390-398`, rules of engagement; `ROADMAP.md:90-122`, Phase C items.
- **Formatting-library behavior:** `ast.unparse`, LibCST, and parso are evaluated as candidate technologies in this design; no claim is made that STEWARD currently depends on or uses them. No dependency file was read or changed in C3-R because dependency changes are forbidden for this batch.

**Evidence gaps:** the authorized context did not include a C3 implementation, patch artifact format, content-edit journal entry, source-file replacement primitive, or C3 UI; therefore this review specifies required behavior but makes no claim that any of it exists today. Exact portable atomic-replacement behavior, AST anchor edge cases, and third-party library version behavior require focused implementation-batch research before code is written.
