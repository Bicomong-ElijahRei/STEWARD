# STEWARD — C4 Execution Safety Review

**Document status:** Complete design/threat review; no executor authorized  
**Review batch:** C4-R  
**Decision:** **PROCEED** with the pure C4-I1 controller; **DEFER** C4-I2 execution until its OS-level isolation requirements are satisfied  
**C4 status after this review:** **BACKLOG**  
**Baseline reviewed:** `8dfd1a9d6f9944a5a0690d4f491344f1e82a6255` (`docs(patch): record tier-label correction and backlog the dialog worker`)  
**Scope of this document:** design and safety review only; it adds no executor, command, sandbox, GUI wiring, provider call, patch-application path, or runtime behavior

---

## 1. Scope and non-goals

### 1.1 In scope

C4 is the future bounded self-healing capability described by PLAN as a `lint/run -> read stderr -> patch -> retry` loop with a hard iteration bound and sandbox (`PLAN.md`, `PHASE C — Swarm & Code Intelligence`, C4 item). A future C4 implementation must coordinate execution observations with the existing C3 patch-review path, but it must not merge those two authorities.

This review determines:

1. what code execution may be authorized;
2. what isolation C4 requires before an executor may exist;
3. how approval, iteration, observation, journaling, and failure semantics must work; and
4. what a future executor batch must prove before it can be merged.

This review does not implement any of those capabilities.

### 1.2 Explicit non-goals and ownership boundaries

- **This batch implements no executor.** There is no subprocess launcher, shell construction, interpreter invocation, linter invocation, test invocation, or command runner here.
- **This batch implements no sandbox.** There is no user, container, job object, restricted token, firewall, ACL, quota, namespace, or temporary-copy mechanism here.
- **C4 must not become a patch applier.** The existing C3 path creates and approves an immutable exact-diff artifact in `PatchReviewManager.propose()` (`agents/patch_review.py`) and applies only that approved artifact through `PatchReviewManager.apply()` / `PatchReviewManager._apply()` (`agents/patch_review.py`). C4 must call a proposal request, not an apply operation.
- **C3 approval remains byte approval, not execution approval.** `PatchReviewManager.approve()` binds a single-use approval ID to the pending immutable artifact, plan, epoch, workspace fingerprint, source/output hashes, and diff hash (`agents/patch_review.py`, `PatchReviewManager.approve`). `PatchReviewManager._consume_approval()` re-verifies and consumes that approval (`agents/patch_review.py`, `PatchReviewManager._consume_approval`). None of those functions starts a process.
- **No GUI or provider behavior is added.** The existing Syntax path is deliberately text-only and has no filesystem or process-execution API (`ARCHITECTURE.md`, `Conversation and Syntax boundaries`; `agents/coding_agent.py`, role recorded in `ARCHITECTURE.md`, `Module roles`).
- **No new user-facing capability is claimed.** C4 remains BACKLOG; only a pure coordination controller may exist after this review.
- **No source content belongs in a journal.** The current content-replacement review explicitly requires metadata-only journal evidence and source-free records (`docs/ast_patch_review.md`, `Journal and recovery`, Section 7.1).

### 1.3 Verified starting point

- PLAN requires each code-execution feature to pass its own safety batch before merge (`PLAN.md`, `PHASE C — Swarm & Code Intelligence`, gate immediately before C1). C4 is still BACKLOG with acceptance for bounded termination, sandbox containment, and per-iteration logging (`PLAN.md`, C4 item).
- The current C3 staging core performs analysis and staging only: it has no path resolution, filesystem access, mutation, approval, persistence, journal, undo, target import, execution, lint, or test surface (`ARCHITECTURE.md`, `AST patch staging and admitted replacement rules`).
- The current C3-I3 facade separates proposal, immutable exact-diff approval, and guarded apply (`agents/patch_review.py`, `PatchReviewManager.propose`, `PatchReviewManager.approve`, `PatchReviewManager._consume_approval`, and `PatchReviewManager.apply`). There is no executor in that module.
- The current operation journal serializes users with a bounded cross-process lock (`agent/journal_lock.py`, `operation_journal_lock`) and persists through a unique same-directory temporary file, flush, `fsync`, and atomic replacement (`agents/file_agent.py`, `FileAgent._save_operation_log_locked`). Mutation intent is durable before disk mutation and completion is durable afterward (`agents/file_agent.py`, `FileAgent._begin_mutation` and `FileAgent._complete_mutation`).
- An interrupted journal intent is reloaded as `uncertain`, not success (`agents/file_agent.py`, `FileAgent._load_operation_log`). This is the required truthfulness precedent for a crash around an executor call.

### 1.4 New threat class

C3 concerns **bytes on disk**: approving and atomically replacing admitted file content. C4 concerns **running code**. Once a process starts, it may use every capability granted to the STEWARD process: read reachable files, write reachable files, open network connections, inherit environment variables, spawn children, consume CPU and memory, emit unbounded output, or alter the machine through those permissions. A syntactically valid patch can therefore be harmless as bytes and dangerous when executed.

C4 therefore requires two independent gates:

1. the existing C3 exact-diff, single-use approval gate for every proposed patch; and
2. a separate, explicit, bounded execution authorization for every future invocation.

Neither gate implies the other.

---

## 2. Threat model

### 2.1 Adversaries and failure sources

The relevant adversary includes a malicious or confused model, a manipulated provider response, hostile repository content, compromised dependencies, a stale authorization, an accidental infinite loop, another local process, and failures of the operating system or sandbox itself.

| Threat | Consequence if uncontrolled | Required C4 control |
|---|---|---|
| Arbitrary code execution | Malicious source or dependency code can act with STEWARD's OS identity | Fixed command profile, no shell, explicit execution grant, OS-level isolation, least privilege |
| Resource exhaustion | CPU, memory, disk, process, or handle exhaustion can degrade or hang the host | Job/process-tree limits, wall/CPU/memory/output/disk quotas, bounded descendants |
| Network egress | Data can be exfiltrated or hostile content fetched | Default-deny egress enforced outside the child process; allowlist only if explicitly justified |
| Filesystem writes outside workspace | Code can alter source, configuration, credentials, or unrelated user data | Read-only baseline; disposable writable copy; deny secrets/AppData/home; isolated temp store |
| Secret exfiltration through stdout/stderr | Credentials, tokens, environment values, or source can leak to the journal or provider | Scrubbed environment, minimal secret exposure, bounded capture, deterministic redaction before any provider use |
| Environment/PATH poisoning | The child may resolve an attacker-selected interpreter, plugin, library, or helper | Absolute executable identity, isolated environment, cleared/inherited variables only by allowlist, no current-directory import |
| Fork bombs or child-process trees | The child can escape a timeout that targets only the parent process | Job/process-tree containment and kill-on-close; descendant accounting |
| Infinite or huge output | Memory, disk, UI, journal, and provider context can be exhausted | Streaming byte caps, truncated capture, cumulative output budget, provider-context cap |
| Symlink/junction and race tricks | A path can escape the selected root or swap between check and use | Handle-based or reparse-aware controls, isolated copy, no reliance on path checks alone |
| Model steering into harmful commands | A generated command can execute arbitrary tools or exfiltrate data | Model may select only an enum/profile; the app owns argv and all arguments |
| Output parsing confusion | Malicious output can steer the next iteration or impersonate a success signal | Strict typed schema, length bounds, no command text in model context, explicit parser failures |
| Approval replay/staleness | An old grant can authorize new code or a different workspace | One-use token bound to command profile, target identity/hash, workspace fingerprint, epoch, expiry |
| Journal failure around execution | History can falsely claim a command did not run or did succeed | Intent before launch, outcome after, atomic durable journal, `uncertain` on interrupted intent |
| Executor or host crash | Orphaned children or half-known effects can survive the parent | Process-tree cleanup, bounded startup, truthful recovery state, manual reconciliation |
| Provider cancellation/confusion | A stale result may continue a newer loop | Loop/run epoch and cancellation token checked at safe boundaries |

### 2.2 Required security properties

A future C4 must establish all of the following:

1. **Fixed command surface:** the model never supplies a command line, executable name, shell fragment, arbitrary interpreter argument, or user-supplied command.
2. **No shell:** commands are launched from an argv vector with shell invocation disabled.
3. **Explicit execution grant:** execution has its own single-use, expiring authorization separate from patch approval.
4. **Exact patch gate:** C4 never applies a patch automatically; every patch goes through the existing C3 exact-diff, single-use approval path.
5. **OS-enforced isolation:** process containment, resource limits, network denial, and filesystem restriction are enforced by the operating system or a stronger isolation boundary, not by cooperation from the child.
6. **Controller-owned bounds:** iteration count, wall clock, cumulative output, and termination decisions are enforced outside the executor.
7. **Bounded observations:** stdout/stderr are streamed under byte caps and deterministically truncated.
8. **Secret hygiene:** secrets are removed from child inputs where possible and redacted before observations reach a provider prompt or durable journal.
9. **Truthful recovery:** an interrupted execution intent is `uncertain`, never presumed safe to retry.
10. **No shell/PATH authority:** no model-controlled path, working directory, environment value, or interpreter selection can influence command resolution.


---

## 3. Command policy decision

### 3.1 Decision

**C4 v1 may run only fixed, application-defined command profiles.** It must not accept arbitrary user commands, model-authored command strings, or commands assembled by concatenating model output.

Each profile must have:

- an application-selected absolute executable identity;
- a fixed argv template owned by the application;
- no shell (`shell=False` semantics);
- no model-supplied executable, option, environment assignment, working directory, redirect, wildcard, or command string;
- an enum profile ID that the model may request only if it needs to choose among pre-approved actions;
- exact target arguments selected by the application from an explicitly admitted workspace and a small fixed target set;
- a separately recorded execution authorization that binds the profile, target, source fingerprint, workspace fingerprint, epoch, limits, and expiry.

The argv vector must be built from typed values, not rendered into a command string. Shell metacharacters in a path must remain ordinary argv data. The executable must be resolved and identity-checked by the application, not selected through `PATH` by the child.

### 3.2 Recommended v1 profile set

The future executor may support only these conceptual profiles, each with fixed argument construction:

1. **Approved interpreter test profile:** the application's pinned Python executable, isolated mode, fixed test-module identifier(s) selected from a reviewed test plan, and fixed runner options. It may not accept an arbitrary test expression from the model.
2. **Approved linter profile:** a pinned linter executable and pinned configuration, with only an admitted relative target passed as argv. The linter and configuration must be present and identity-checked before authorization; absence is a clean refusal.
3. **Syntax-only profile, if needed:** an application-owned parser check that does not import or execute the target. This is analysis, not a substitute for the execution boundary.

No profile may include `shell=True`, `cmd.exe`, PowerShell, `sh`, `bash`, `python -c`, `python -m` with a model-selected module, `eval`, dynamic imports, package installation, VCS/network commands, arbitrary scripts, or output redirection chosen by the model.

### 3.3 Explicitly prohibited in v1

- user-supplied arbitrary commands;
- model-supplied command lines, flags, shell fragments, scripts, or interpreter snippets;
- command construction from template interpolation of model output;
- shell lookup through `PATH`, `PATHEXT`, `COMSPEC`, or current-directory resolution;
- inherited environment wholesale;
- arbitrary working directories;
- recursive or user-expanded path arguments;
- downloading dependencies or executing package installers;
- letting the child select its own interpreter, linter plugin, config, or test target.

### 3.4 Model authority boundary

The model's role ends at requesting one approved profile/action from a strict enum and describing the intended repair. The application resolves that request to an immutable argv vector, verifies target admission and current hashes, obtains a matching execution grant, and invokes the executor. The model cannot see or alter the grant, environment, executable identity, limit set, or final argv.


---

## 4. Isolation decision

### 4.1 Decision

**A future executor is not safe to merge if isolation is only implemented with Python-level `subprocess` arguments, environment dictionaries, `cwd`, and timeouts.** Those controls reduce accidental behavior but do not establish containment against code that has already started.

C4-I2 must use an OS-level isolation boundary on Windows. Recommended options, in preference order, are:

1. a disposable Windows Sandbox/VM/container environment with no host credentials and controlled networking;
2. a hardened local worker in a Windows Sandbox/VM with an explicit host communication channel;
3. a Windows Job Object plus restricted token/AppContainer-equivalent controls **only if** focused tests prove job-tree termination, memory/CPU limits, filesystem denial, and network denial for the complete child tree.

A plain Python child process with `CREATE_NEW_PROCESS_GROUP`, a timeout, a scrubbed environment, and a fixed cwd does **not** satisfy this decision.

### 4.2 Required isolation properties

#### Working directory and path boundary

- Set cwd to a dedicated disposable iteration directory, never the real workspace and never a directory containing untrusted configuration.
- Prefer a read-only, hash-verified copy of admitted source for execution.
- Allow writes only to an isolated scratch/output directory explicitly created for the run.
- Deny access to the real source workspace during execution, or restore it from a verified copy after each iteration. Source edits occur only through C3.
- Deny AppData, user profile, credential stores, SSH/config directories, browser/profile data, and unrelated drives by default.
- Treat symlinks, junctions, reparse points, hard links, alternate data streams, and device paths as escape candidates. Path canonicalization alone is not a complete race defense.

#### Environment scrubbing

- Start from an empty environment, then add only required variables such as an isolated cache/temp location, a minimal locale, and explicitly approved tool configuration.
- Do not inherit provider keys, database credentials, application secrets, user tokens, proxy credentials, or arbitrary STEWARD environment variables.
- Set `PATH` to a fixed empty or tool-specific directory; resolve the executable absolutely before launch.
- Disable user site packages (`-s`/`-I` as applicable), `PYTHONSTARTUP`, `PYTHONPATH`, `PYTHONHOME`, `PYTHONWARNINGS` injection, dynamic-loader paths, and current-directory import.
- Do not expose source paths or secret-bearing configuration through environment variables.

#### Network denial

- Default-deny outbound network at the OS/firewall/VM boundary, not with application code in the child.
- Deny DNS as well as direct IP traffic.
- Do not permit loopback channels to STEWARD unless a future design proves and authenticates a narrow protocol.
- Any exception requires a separate reviewed policy and must not be inferred from command output.

#### Filesystem restrictions

- Execute against a disposable copy or snapshot, not the authoritative workspace.
- Deny writes to the authoritative workspace, application data, secrets, and unrelated user paths.
- Use OS ACLs, container mounts, VM shares, or equivalent controls; Python `cwd` alone is insufficient.
- Keep source and output provenance explicit: record the admitted source hash, the isolated copy hash, and the returned artifact hash.

#### Resource limits


### 4.3 What Python-level subprocess controls can and cannot enforce on Windows

Python-level controls can enforce or assist with:

- selecting an exact executable argument vector;
- disabling shell interpretation;
- setting a starting working directory;
- supplying a deliberately constructed environment;
- closing inherited standard handles where the API permits;
- waiting with a deadline and terminating/reaping the immediate child; and
- bounding bytes read from the child's pipe if the reader is implemented incrementally.

Python-level controls alone **cannot reliably prove or enforce**:

- that the complete descendant process tree has stopped;
- total CPU, private memory, handle, process, or scratch-disk consumption;
- denial of filesystem paths, reparse targets, devices, or alternate data streams;
- denial of direct-IP, DNS, proxy, loopback, or side-channel egress;
- that a poisoned interpreter/plugin/config was not loaded;
- that no external process raced a checked path;
- that cancellation completed within a strict wall-clock bound;
- that a child did not retain credentials through inherited handles, side channels, crash dumps, or filesystem artifacts; or
- that no code outside the observable process tree performed side effects.

Windows Job Objects can address process-tree lifetime and several resource counters, but they must be implemented and tested as a separate native/Windows boundary. Restricted tokens, ACLs, AppContainer, firewall rules, or a VM may be required for the remaining properties. The point is not that one API is impossible; it is that `subprocess` plus a timeout is not a sandbox.

### 4.4 Honest limitation

Without OS-level sandboxing, C4 cannot honestly claim “cannot escape sandbox” as required by the PLAN C4 acceptance line (`PLAN.md`, C4 item). Therefore the executor remains deferred rather than being implemented with weaker controls and a misleading claim.

---

## 5. Approval decision — critical

### 5.1 Decision

**C4 must never auto-apply a patch.**

Every iteration that proposes a repair must go through the existing C3 workflow:

1. request a proposal through the C3 proposal interface;
2. materialize and persist an immutable exact-diff artifact;
3. show the exact diff;
4. obtain the existing single-use exact-diff approval bound to artifact, plan, epoch, workspace fingerprint, source/output hashes, and diff hash; and
5. apply only through the existing C3 apply path.

The current implementation performs those responsibilities in `PatchReviewManager.propose()`, `PatchReviewManager.approve()`, `PatchReviewManager._consume_approval()`, and `PatchReviewManager.apply()` (`agents/patch_review.py`). C4 must treat that path as an external, mandatory gate and must not duplicate or weaken it.

The controller may request a proposal step through an injected callback. It must not accept or call a patch-application callback. The callback boundary is not permission to apply: a proposal is only a request for review.

### 5.2 Why C3 approval is insufficient

C3 approval says: **these exact bytes may replace these exact admitted source bytes.** It does not say: **these bytes may be imported, interpreted, tested, linted, or run.** The latter is a different authority with different consequences and must never be inferred from the former.

Likewise, successful execution does not imply permission to patch. A separate C3 exact-diff approval is still required.

### 5.3 Recommended v1 execution authorization

Execution requires a separate, explicit, one-use **execution grant**. The grant should be created by the application only after the user sees and authorizes:

- the fixed command profile ID and the exact argv preview;
- the admitted target identities and current source hashes;
- the canonical workspace/copy fingerprint;
- the run ID and conversation epoch;
- the hard iteration, timeout, total-clock, process, memory, CPU, output, and disk limits;
- the network policy;
- the sandbox/isolation identity and expiry; and
- the fact that execution can run arbitrary code inside that boundary.

The grant must be bound to those values, expire quickly, be consumed once, and be invalidated by target/source/workspace/epoch/profile/limit changes. It must not authorize a patch application. It must not authorize a command outside the approved profile.


---

## 6. Iteration bounds

### 6.1 Decision

All bounds are controller-owned and checked before each iteration and during observation capture. The executor is not trusted to enforce them.

Recommended v1 defaults:

| Bound | Recommended default | Enforcement owner |
|---|---:|---|
| Hard maximum iterations | 3 | Controller counter, checked before every iteration begins |
| Per-iteration wall timeout | 60 seconds | Controller/executor supervisor plus OS process-tree deadline |
| Total run wall clock | 180 seconds | Controller monotonic deadline |
| Cumulative stdout/stderr bytes | 1 MiB | Streaming capture in controller/executor boundary |
| Per-stream bytes per iteration | 256 KiB | Streaming capture |
| Journal observation excerpt | 16 KiB per iteration | Controller before journal write |
| Provider observation excerpt | 16 KiB total per request | Controller/provider adapter before prompt assembly |
| Maximum child processes | 1 parent plus a fixed small descendant cap | OS process/job accounting |
| Maximum concurrent iterations | 1 | Controller |

### 6.2 Structural hard bound

The controller must increment and check its own iteration count **before** the iteration begins. The executor must not be able to request, restart, or reset the loop. Reaching the maximum ends the run with a deterministic `bound_reached` state even if the last observation was a failure.

A future mutation proof must weaken or remove that pre-iteration count check and demonstrate that the focused test fails by observing an extra executor invocation.

### 6.3 Termination conditions

The controller terminates deterministically on:

- a strict success signal from a valid typed observation;
- the hard iteration bound;
- total wall-clock exhaustion;
- an unrecoverable executor/parser/authorization error;
- cancellation observed between iterations;
- repeated identical failures reaching the configured threshold;
- an execution-grant refusal or expiry; or
- a durable journal pre-write failure, which prevents the iteration from starting.


---

## 7. Observation handling

### 7.1 Capture bounds

The executor must read stdout and stderr incrementally through bounded pipes. It must never call an unbounded `communicate()`-style accumulation with an unbounded result in memory. The controller must enforce, or verify enforcement of:

- per-stream byte cap;
- per-iteration combined byte cap;
- cumulative run byte cap;
- maximum individual line length;
- maximum retained excerpt length; and
- elapsed capture/deadline behavior.

A stream that exceeds its cap is terminated or closed according to the fixed policy and is marked truncated. Truncated output is incomplete evidence.

### 7.2 Deterministic truncation

Truncation must retain a deterministic prefix (or a documented deterministic head/tail form) and report:

- stream name;
- original observed byte count;
- retained byte count;
- whether truncation occurred; and
- the cap that was reached.

The journal must not contain the complete oversized output. It may contain the bounded excerpt plus counts and truncation metadata.

### 7.3 Secret redaction

Before an observation reaches a durable journal or any provider prompt, the application must redact content that resembles secrets. At minimum, the future executor must cover:

- environment-style secret assignments;
- provider/API key and token patterns;
- authorization and cookie headers;
- private-key blocks;
- known STEWARD secret-key/database material; and
- configured secret values loaded from the application's secret store.

Redaction must be deterministic, preserve a redaction marker and count, and run before prompt assembly. It reduces disclosure but cannot prove that arbitrary secret encodings or transformed data are absent. Therefore secrets should not be present in the child environment in the first place.

Provider context must use only a separately bounded, redacted excerpt. The full local observation may remain in the restricted local journal only if its own byte cap and storage policy permit it.

---

## 8. Journal and recovery

### 8.1 Required write-ahead sequence

Each iteration uses two durable records, following the existing write-ahead pattern:

1. **Intent** is durably written before the executor is called. It includes run ID, iteration number, command profile ID, target/fingerprint references, grant ID, limits, and `state: intent`. It contains no source content, command output, or unbounded text.
2. **Outcome** is durably written after the executor returns or fails. It includes the bounded/redacted observation summary, exit/classification metadata, truncation/redaction counts, and a terminal state.

---

## 9. Failure and abort semantics

### 9.1 Executor crash

- If the executor process crashes before a valid observation, the controller records `executor_crash` or `unrecoverable_error` with bounded stderr and exit metadata when available.
- If the executor controller itself crashes, the durable intent remains. Recovery treats it as `uncertain`, not as “not run.”
- Any surviving child tree must be terminated by the isolation boundary before retry or another iteration.

### 9.2 Timeout

- A per-iteration timeout is `timeout`; total run timeout is `total_timeout`.
- The isolation boundary must kill the full process tree.
- Output captured before termination is retained only within bounds and marked truncated if incomplete.
- No success is inferred from a timeout.

### 9.3 Non-zero exit

- A non-zero exit is a bounded failure observation, not an executor crash.
- The controller may request a C3 proposal if the observation is sufficient and safe.
- The command remains in the fixed failure class until the next observation; repeated identical failure detection uses the bounded signature.

### 9.4 Unparseable output

- The future executor must return a strict typed schema. Raw tool output must never be interpreted as controller instructions.
- Missing required fields, invalid enums, invalid byte counts, malformed encoding, or conflicting status fields are `unrecoverable_error` or `parse_error`.
- The controller does not guess success from text such as “passed,” “ok,” or a model-authored marker.
- A parse error is recorded with bounded raw evidence only if safe and redacted.

### 9.5 Cancellation mid-iteration

- The executor terminates the process tree and returns a typed cancellation/timeout outcome.
- The controller durably records the non-success outcome.
- Cancellation observed between iterations stops before the next intent and records `cancelled`.
- A cancellation racing with a completion is resolved by the durable ordering: whichever terminal record is committed first determines the recorded state; later conflicting writes are refused.

### 9.6 Repeated identical failures

- The controller hashes a bounded normalized failure signature and stops when the configured consecutive threshold is reached.
- The run state is `repeated_failure` and records the signature/count, not unbounded output.

---

## 10. Residual risks, open questions, and recommendation

### 10.1 Open questions for a future executor batch

1. Which Windows isolation primitive will be the supported v1 baseline: Windows Sandbox/VM, a hardened container, or Job Object plus restricted token/ACL/firewall controls? The choice determines the dependency and test strategy.
2. How will the application transfer admitted source into the isolated boundary and authenticate returned artifacts without creating a host command channel?
3. Which exact linter executable/configuration, if any, is already approved and dependency-audited? No linter dependency is established by this review.
4. Which fixed test targets are allowed for a given reviewed plan, and how are their identities bound to the execution grant?
5. What source-file types, encodings, line endings, and path classes may enter an isolated copy?
6. How will deterministic redaction be configured for user-defined provider secrets while avoiding false assurance?
7. What host capacity thresholds should trigger refusal before a run starts?
8. Should the pure controller's proposal callback be exposed in the GUI now, or remain internal until C4-I2 has an execution grant and isolation provider?

### 10.2 Residual risks

- **No Python-only sandbox:** fixed argv, environment scrubbing, and deadlines do not contain hostile code. This is why C4-I2 remains deferred.
- **Dependency and interpreter trust:** even an isolated interpreter may load compromised standard-library/site-package code; the executable and environment must be pinned and verified.
- **Escape via permitted artifacts:** output files, logs, crash dumps, caches, or generated files can still consume storage or contain secrets even when direct writes are denied.
- **Side channels:** timing, entropy, shared kernel services, and metadata can leak information even without ordinary network or file access.
- **Race and reparse limitations:** path checks cannot completely exclude a cooperating or adversarial external filesystem actor unless handles, ACLs, or VM boundaries are used.
- **Provider exposure:** a model can still steer behavior indirectly through a permitted command's arguments, environment, generated code, or repository content. Fixed profiles narrow but do not eliminate this.
- **Redaction imperfection:** secret redaction is best-effort and cannot recognize every encoded or transformed secret.
- **False success:** executors can lie through exit codes or output. The controller can validate only bounded structural signals, not semantic correctness of arbitrary code.
- **Resource accounting gaps:** Windows job/process controls may not cover every resource equally across Windows versions.
- **Journal confidentiality:** bounded local observations may still contain sensitive repository information even after best-effort redaction.
- **Human fatigue:** repeated approval prompts can train users to approve reflexively; the UI must make scope and risk salient.
- **OS-level isolation availability:** host policy, antivirus, enterprise controls, or missing virtualization may make the approved boundary unavailable. In that case execution must be refused, not silently downgraded.

### 10.3 Recommendation

**PROCEED with C4-I1 only, and DEFER C4-I2 and all real execution.**

The pure controller is justified because it adds no execution authority: it can enforce iteration structure, coordinate injected interfaces, bound observations, and journal truthful iteration state while remaining unable to apply patches. Its existence does not satisfy or weaken the sandbox acceptance criterion.

Do not write the executor until a focused C4-I2 design selects and validates an OS-level Windows isolation boundary. At minimum, the future batch must prove process-tree termination, CPU/memory/process/output/disk limits, default-deny network behavior, filesystem isolation from real source/AppData/secrets, explicit execution-grant binding, C3 exact-diff non-bypass, crash recovery, and no-auto-apply behavior.

If a future batch cannot prove those properties on the supported host, the correct outcome is **defer C4 again** rather than weaken the boundary.

- Retrying with a changed command profile or target requires a new explicit execution grant and does not evade the hard iteration count.


---

## 11. Acceptance criteria for the future executor batch (C4-I2)

All criteria are required. A feature-only test is insufficient.

1. **Isolation proof:** on the supported Windows host, tests demonstrate that the child cannot write the authoritative workspace, AppData, user profile, or unrelated roots; direct-IP, DNS, proxy, and loopback egress are denied by an OS-level control.
2. **Process-tree proof:** timeout and cancellation kill and reap the complete descendant tree, including children spawned after the initial process starts.
3. **Resource proof:** CPU, wall clock, memory, process/descendant count, handle count, scratch-disk, and output caps are enforced outside cooperative child code and remain within documented host margins.
4. **Fixed command proof:** model and user input cannot alter the executable, argv template, interpreter, plugin/config, environment, cwd, or target beyond the approved enum/profile and admitted target.
5. **No shell:** tests prove shell metacharacters remain argv data and no shell is launched.
6. **Absolute executable and environment proof:** executable identity is pinned and checked; the child receives no provider keys, database/key material, user tokens, `PYTHONPATH`, current-directory import, or unapproved `PATH` entries.
7. **Separate execution grant:** execution requires a single-use, expiring grant bound to command profile, exact target/source/workspace fingerprint, epoch, run, limits, and isolation identity. Missing, stale, replayed, changed, expired, and wrong-scope grants execute nothing.
8. **C3 remains mandatory:** every proposed patch is shown as an exact diff and uses the existing single-use C3 approval. C4 never auto-applies, bypasses, weakens, or reuses an execution grant as patch approval.
9. **No-auto-apply proof:** spies prove the controller/executor cannot reach any patch-application path; a fake applier that raises is never called.
10. **Hard iteration bound:** a fake executor that always fails terminates at exactly the configured maximum. A mutation that weakens the controller's pre-iteration count check turns the focused test RED, and restoration returns it GREEN.
11. **Controller-owned time/output bounds:** the executor cannot extend the iteration count, per-iteration timeout, total wall clock, cumulative output budget, or observation excerpt caps by returning hostile values.
12. **Termination semantics:** success, bound, unrecoverable error, timeout, cancellation, repeated identical failure, parse error, authorization refusal, and journal failure each have deterministic states and journal records.
13. **Write-ahead ordering:** durable intent precedes every launch and durable outcome follows every return; an intent-write failure produces zero launches, and an outcome-write failure is `uncertain`, not success.
14. **Crash recovery:** an interrupted intent reloads as `uncertain`; no automatic retry occurs until the process tree is known stopped and the user performs explicit reconciliation.
15. **Bounded observation:** oversized stdout/stderr is truncated deterministically with original/retained byte counts and truncation flags; no journal, UI, or provider payload contains unbounded output.
16. **Secret hygiene:** known and pattern-shaped secrets are redacted before provider use; the child environment does not contain avoidable secrets; redaction markers/counts are deterministic.
17. **Journal privacy and durability:** records contain metadata and bounded/redacted excerpts, not source or unbounded output; publication uses flush/fsync/atomic replacement and cross-process serialization.
18. **No stale-loop behavior:** run/plan/workspace/epoch changes invalidate grants and stop the loop; cancellation at every safe boundary is truthful and deterministic.
19. **Hostile repository proof:** malicious source, test, linter plugin, filename, symlink/junction/reparse target, environment value, and output cannot escape the approved boundary or influence command construction.
20. **Full regression proof:** dedicated RED → GREEN and mutation-proof tests pass, the existing full suite remains green with only the known Windows symlink-privilege skip, validator checks pass, compileall and diff checks pass, and no production AppData state or real source file is touched by tests.

---

## Evidence index and evidence gaps

- **Phase C execution gate and C4 backlog:** `PLAN.md`, `PHASE C — Swarm & Code Intelligence`, gate and C4 item.
- **C3 proposal and immutable artifact:** `agents/patch_review.py`, `PatchReviewManager.propose`.
- **C3 exact-diff approval and single-use consumption:** `agents/patch_review.py`, `PatchReviewManager.approve` and `PatchReviewManager._consume_approval`.
- **C3 mutation path:** `agents/patch_review.py`, `PatchReviewManager.apply` and `PatchReviewManager._apply`.
- **Atomic journal persistence:** `agents/file_agent.py`, `FileAgent._save_operation_log_locked`.
- **Write-ahead intent/completion:** `agents/file_agent.py`, `FileAgent._begin_mutation` and `FileAgent._complete_mutation`.
- **Interrupted-intent truthfulness:** `agents/file_agent.py`, `FileAgent._load_operation_log`.
- **Cross-process journal serialization:** `agent/journal_lock.py`, `operation_journal_lock`.
- **Precedent review structure and source-free journal rule:** `docs/ast_patch_review.md`, Sections 1, 7, 12, and 13.

**Evidence gaps:** this review was intentionally design-only. It did not inspect or design a concrete Windows Job Object, restricted token, firewall, AppContainer, VM/container integration, process-launch implementation, linter dependency, provider observation adapter, or GUI execution-grant flow. Those choices require a focused future implementation batch. No claim in this document asserts that an OS-level sandbox or executor currently exists.

### 9.7 Journal failure

- **Before intent:** the iteration must not start.
- **After execution but before outcome:** state is `uncertain`; never claim success or safe retry.
- **Terminal-state write failure:** return an explicit journal/uncertain state to the caller and preserve the last durable truth.

### 9.8 Authorization failure

- Missing, expired, replayed, stale, wrong-epoch, wrong-target, wrong-profile, or changed-workspace authorization stops the run before execution.
- It is not a retryable executor failure and must never be downgraded to ordinary output.


The existing pattern is evidenced by `FileAgent._begin_mutation()` and `FileAgent._complete_mutation()` (`agents/file_agent.py`) and its atomic persistence in `FileAgent._save_operation_log_locked()` (`agents/file_agent.py`). Cross-process serialization should reuse `operation_journal_lock()` (`agent/journal_lock.py`) or an equivalent dedicated lock so cooperating STEWARD processes cannot interleave records.

### 8.2 Atomicity and ordering

A journal implementation should use the same durable publication pattern: unique same-directory temporary file, flush, `fsync`, and atomic replacement. A pre-iteration intent-write failure must prevent the executor call. An outcome-write failure after execution must produce an `uncertain` controller state and a truthful recovery marker; it must not report success.

### 8.3 Crash states

| State at crash | Truthful interpretation | Recovery rule |
|---|---|---|
| No intent for the next iteration | Previous iteration completed and was recorded | Resume only under a new explicit run authorization and fresh checks |
| Intent exists, no outcome | Executor may not have started, may have run, or may still have descendants running | Mark `uncertain`; reconcile/quarantine before any retry; never auto-retry |
| Outcome exists as failure/success | Executor returned and that classification was durably recorded | Continue only if all other bounds/authorizations permit |
| Outcome exists as uncertain | Effects or grant consumption cannot be fully proven | Stop and require manual reconciliation |

The current journal already converts interrupted mutation intents to `uncertain` on load (`agents/file_agent.py`, `FileAgent._load_operation_log`). C4 must preserve that truthfulness rather than assuming a missing outcome means “never ran.”

### 8.4 Retention and privacy

Journal records are metadata plus bounded/redacted excerpts. They must not contain source files, patch source text, full environment dumps, unbounded output, raw secrets, or provider payloads. Retention and pruning must not remove unresolved `uncertain` records or their evidence.

### 6.4 Repeated identical failures

Failure identity must use a bounded deterministic signature: explicit failure class/code plus a hash of the bounded normalized observation. The controller must not retain unbounded output to compare failures. Two identical consecutive signatures normally trigger immediate termination; a configurable threshold of two is recommended. A changed failure signature resets the consecutive count but does not relax the hard iteration bound.

### 6.5 Cancellation boundary

Cancellation is checked between iterations, after the prior outcome is durably recorded and before the next intent is written. A cancelled run stops at that safe boundary and records `cancelled`. If cancellation arrives during execution, the executor must terminate the process tree and report a typed timeout/cancellation outcome; the controller must not claim success.

### 5.4 Authorization sequence

For each iteration, the safe sequence is:

1. controller writes durable intent;
2. controller checks cancellation and all run bounds;
3. controller validates the approved command profile, target, hashes, workspace, and current execution grant;
4. controller invokes the executor through the isolated boundary;
5. executor returns a typed, bounded observation;
6. controller writes durable outcome;
7. controller may request a C3 proposal from the bounded observation;
8. a human separately approves the exact C3 diff;
9. only C3 may apply that exact diff; and
10. the controller starts a new iteration only with a valid, unconsumed execution grant.

If a proposal is pending approval, the loop waits or stops; it must not race ahead or treat pending approval as success.

- Enforce a wall-clock deadline outside the child.
- Enforce CPU time, working-set/private memory, process count, descendant-process count, handle count, and scratch-disk/output bytes with OS controls where available.
- Kill the entire process tree on timeout/cancellation, not only the immediate child.
- Account for descendants created before and after the parent exits.
- Reserve sufficient host capacity so the cap protects the host rather than merely matching it.

#### Output limits

- Stream stdout and stderr; never accumulate an unbounded child stream in memory.
- Cap per-stream bytes, per-iteration combined bytes, cumulative run bytes, and journal/provider excerpt bytes.
- Report original observed byte count, retained byte count, and truncation explicitly.
- Treat a truncated stream as incomplete evidence, not as a complete error message.

