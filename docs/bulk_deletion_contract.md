# BULK-1 bulk-deletion preparation contract

**Status:** BULK-1 preparation core implemented in commits
`9f37d9fd333e4d3bb6b405bea99a8b3d45609176` and
`62ae399396c59b9bd0fd6674bb9540bc4233fa38`; BULK-2 bound recycle-bin
execution implemented in `0a9045d37ab2f5144484816946cead145c32a8e3`.

**Amendment — 2026-11-28 (BULK-2):** the six decisions below remain binding.
This amendment supersedes only the former preparation-only and ten-tool statements:
exactly two cleanup tools are now model-dispatchable. The model supplies only a
sandboxed `directory`; the application enumerates and binds the exact candidate
set. Every cleanup binding in a multi-call plan is re-verified before the first
removal. Execution is restricted to `send2trash.send2trash`, journal intent is
written before removal, and bulk cleanup is truthfully non-undoable. The active
FileAgent dispatch set is exactly twelve tools.

## Scope and non-goals

BULK-1 prepares a safe preview and approval binding for bulk cleanup. BULK-2
adds exactly two model-dispatchable cleanup tools, `cleanup_temp_files` and
`cleanup_empty_folders`. Both accept only a sandboxed `directory`; application
enumeration supplies the exact immutable candidate binding. Execution uses only
`send2trash`, never permanent removal. The active dispatch set is exactly twelve
tools; `batch_move` remains unreachable.

## The six BULK-1 decisions

### 1. Exposure boundary: exactly two bound cleanup tools

`agent/bulk_deletion_core.py` remains read-only. `agents/file_agent.py` exposes
exactly `cleanup_temp_files` and `cleanup_empty_folders`. Their model arguments
are restricted to `directory`; any supplied path list or extra argument is
refused. The application replaces those arguments with the canonical root,
ordered candidates, identity/candidate policies, and SHA-256 binding. Removal
lives only in `agent/bulk_cleanup_execution.py` and uses `send2trash.send2trash`.

### 2. Canonical roots and sandbox containment

The requested root and every allowed root are canonicalized with
`realpath(abspath(...))`. The canonical root must be a directory and must be
contained by at least one canonical allowed root under `commonpath` and
`normcase` rules. Both the supplied and canonical root are limited to 1,024
characters. A root outside the sandbox is refused before traversal.

### 3. Bounded, link-free traversal with whole-result refusal

Traversal never follows symlinks or Windows junctions and rechecks canonical
containment for every visited path. It refuses the entire enumeration when it
encounters a path longer than 1,024 characters, depth greater than 8, more
than 1,000 regular files, more than 1,000 candidates, or any traversal I/O
error. `os.walk` errors are converted into a typed refusal; partial candidate
output is never returned after such a failure.

### 4. Candidate policy and deterministic ordering

Temporary-file candidates use `.tmp`, `.temp`, `.cache`, `.swp`, `thumbs.db`, and
`desktop.ini` (matched case-insensitively). Diagnostic logs (`.log`) and backups
(`.bak`) are excluded because they are evidence/recovery artifacts rather than
unambiguous temporary files. Empty-directory candidates are the bottom-up closure
of directories whose children are themselves removable empty directories.
Temporary files are sorted by normalized path; empty directories are sorted
deepest-first and then by normalized path. Repeated enumeration of unchanged
content is deterministic.

### 5. Immutable records and an exact ordered-set binding

`CandidateEntry`, `EnumerationResult`, `BoundCandidateSet`, and
`VerificationResult` are frozen dataclasses; candidate collections are tuples.
A candidate's identity is its canonical path, kind, size, and `mtime_ns`.
The SHA-256 binding hash covers the binding version, identity policy, candidate
policy, canonical root, entry count, and every ordered entry's path, kind, size,
and `mtime_ns`. Length framing prevents ambiguous concatenation. The identity
policy is `path-size-mtime-ns-v1`; content bytes are not hashed by this contract.
The candidate policy records the active suffix set or empty-directory closure
rule, so a policy change is drift rather than silently broader authority.

### 6. Whole-set re-verification with typed refusals

Before the first removal, every cleanup binding in the whole plan must match the
approved binding exactly. The whole binding is refused if an entry was added or
removed, an entry's identity changed, path order changed, the root changed, the
identity or candidate policy changed, or either recomputed binding hash differs.
Enumeration failures are typed `EnumerationRefusal` values; drift failures are
typed `RefusalReason` values. No partial acceptance is possible. Journal intent
must persist successfully before removal, and the operation metadata records
`undoable: False`; undo cannot consume an earlier unrelated reversible entry as
a substitute for undoing bulk cleanup.

## Core API

- `enumerate_candidates(root, allowed_roots=..., kind=...)` returns one
  complete `EnumerationResult` or raises `EnumerationRefusal`.
- `bind_candidates(enumeration)` returns an immutable `BoundCandidateSet` with
  the exact-set SHA-256 binding hash.
- `reverify_binding(binding, current)` returns a `VerificationResult`; any
  refusal reason makes `accepted` false.

The only candidate kinds are `TEMPORARY_FILE` and `EMPTY_DIRECTORY`.

## Duplicate-report hashing budget

The adjacent duplicate-report hardening is also part of BULK-1's bounded-read
work. `find_duplicates` hashes at most 64 MiB from one file and 256 MiB across
one report. A file is admitted only when its initially observed size fits both
budgets. Size, `mtime_ns`, device, and inode are compared before and after
hashing. Oversized, inaccessible, changed, and cumulative-budget files are
reported as skipped rather than as unique or duplicate.

## Verification evidence

The implementation has six focused hashing regressions, 28 focused bulk-core
regressions, and focused exposure regressions covering the twelve-tool allowlist,
argument refusal, exact preview, all drift classes, whole-plan preflight,
deepest-first ordering, recycle-bin-only execution, journal ordering, and
non-undoability. The final full discovery suite contains 572 tests, with one
expected Windows symlink-privilege skip; validator checks are 5/5. Targeted
mutation proof killed four hashing guards, 20 bulk-core guards, and removal of
the cleanup re-verification guard. The active dispatch allowlist is exactly
twelve tools.
