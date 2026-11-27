# BULK-1 bulk-deletion preparation contract

**Status:** implemented as an internal, read-only preparation core in commits
`9f37d9fd333e4d3bb6b405bea99a8b3d45609176` and
`62ae399396c59b9bd0fd6674bb9540bc4233fa38`.

## Scope and non-goals

BULK-1 prepares a safe preview and approval binding for a possible future bulk
cleanup operation. It does **not** delete, trash, move, or mutate anything. The
core is not imported by the active `agents/file_agent.py` dispatch path and
does not add a chat tool, schema entry, permission, dependency, or runtime
route. The active dispatch set remains exactly ten tools.

A future destructive implementation must be separately reviewed and approved.
It is intended to use `send2trash`; permanent bulk removal is not being
exposed.

## The six BULK-1 decisions

### 1. Exposure boundary: prepare only, never execute

`agent/bulk_deletion_core.py` reads and stats filesystem entries but contains no
mutation primitive. Its public behavior is enumeration, binding, and
re-verification only. An undeclared legacy cleanup function cannot be called
through a model-issued plan. The active FileAgent schema and dispatch
allowlist remain unchanged.

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

Temporary-file candidates use the exact legacy suffix set: `.tmp`, `.temp`,
`.cache`, `.log`, `.bak`, `.swp`, `thumbs.db`, and `desktop.ini` (matched
case-insensitively). Empty-directory candidates are the bottom-up closure of
directories whose children are themselves removable empty directories.
Temporary files are sorted by normalized path; empty directories are sorted
deepest-first and then by normalized path. Repeated enumeration of unchanged
content is deterministic.

### 5. Immutable records and an exact ordered-set binding

`CandidateEntry`, `EnumerationResult`, `BoundCandidateSet`, and
`VerificationResult` are frozen dataclasses; candidate collections are tuples.
A candidate's identity is its canonical path, kind, size, and `mtime_ns`.
The SHA-256 binding hash covers the binding version, identity policy, canonical
root, entry count, and every ordered entry's path, kind, size, and `mtime_ns`.
Length framing prevents ambiguous concatenation. The identity policy is
`path-size-mtime-ns-v1`; content bytes are not hashed by this contract.

### 6. Whole-set re-verification with typed refusals

Before any future execution, the current enumeration must match the approved
binding exactly. The whole binding is refused if an entry was added or removed,
an entry's identity changed, path order changed, the root changed, the identity
policy changed, or either recomputed binding hash differs. Enumeration
failures are typed `EnumerationRefusal` values; drift failures are typed
`RefusalReason` values. No partial acceptance is possible.

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

The implementation has six focused hashing regressions and 28 focused
bulk-core regressions (34 combined). The full discovery suite contains 562
tests, with one expected Windows symlink-privilege skip; validator checks are
5/5. Targeted mutation proof killed four hashing guards and 20 bulk-core
guards. The bulk-core tests also prove non-mutation, immutable records,
typed refusal behavior, canonical containment, link exclusion, bounds,
deterministic ordering, and that the active dispatch allowlist remains exactly
ten tools.
