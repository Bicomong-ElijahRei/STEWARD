# 🗺️ STEWARD: The Master Blueprint

> **Vision:** To evolve STEWARD from a basic file organizer into an enterprise-grade, autonomous Multi-Agent system with a visually stunning "Cyber-Kawaii" interface.

This document serves as the official technical roadmap for STEWARD. It outlines the architectural upgrades, UI/UX overhauls, and safety mechanisms required to make STEWARD a state-of-the-art desktop AI assistant.

## Release Roadmap

- **v2.1 — Core Safety & Credentials (Done):** canonical sandboxing, immutable
  approval plans, bounded daemon processing, shared encrypted credential storage,
  provider failover, and guarded migration tooling.
- **v2.2 — Visuals & RAG (Done):** Cyber-Kawaii animations, responsive live agent
  constellation, formatted chat states, and persistent grounded RAG ingestion and
  retrieval.
- **v2.3 — Learning & Rules (Done):** deterministic `rules.yaml` categorization,
  priority-ordered matching, LLM bypass for known patterns, manual override
  learning, and visible rule/chat indicators.
- **v2.4 — Hierarchical Swarm & Scheduling (Done):** readable plain-text Markdown
  chat rendering, Cortex-to-specialist delegation with bounded workers, failure
  isolation, Live Feed observability, and restart-persistent recurring file scans.
- **v3.0 — Safe-Intelligence Foundations (Current):** explicit credential rotation,
  generation-safe scheduled scans, bounded Cortex conversation memory, provider-backed
  text-only Syntax assistance, durable write-ahead filesystem history, no-overwrite
  mutation publication, and persistent state relocated to `%APPDATA%\STEWARD`.
  These foundations intentionally do not grant Syntax file-write or code-execution capability.
- **v3.0 — Advanced Code Intelligence & Phase D (Future):** self-healing loops and
  research-backed integrations such as MCP, voice, and remote control. The current codebase
  includes one-file AST patch staging, guarded replacement/recovery, and a user-integrated
  exact-diff Patch Review workflow; C3 self-healing remains future work.

---

## 📑 Table of Contents
- [Phase 0: The Safety & Stability Foundation](#phase-0-the-safety--stability-foundation)
- [Phase A: Core Control & API Management](#phase-a-core-control--api-management)
- [Phase B: The Cyber-Kawaii Experience](#phase-b-the-cyber-kawaii-experience)
- [Phase C: The Swarm & Code Intelligence](#phase-c-the-swarm--code-intelligence)
- [Phase D: Research-Backed Horizon](#phase-d-research-backed-horizon)

---

## 🛡️ Phase 0: The Safety & Stability Foundation
*Goal: Fix critical vulnerabilities identified in the architecture audit before adding new features.*

- [x] **Immutable Execution Plans (TOCTOU Fix):**
  - **Problem:** The current chat approval path can regenerate an operation plan after the user has already approved it, creating a risk of executing unauthorized actions.
  - **Solution:** Update `gui/chat_tab.py` and `agents/file_agent.py`. The exact JSON tool-call plan displayed in the preview must be saved and executed upon approval. Do not prompt the LLM to regenerate the plan.
- [x] **Canonical Path Sandboxing:**
  - **Solution:** Resolve source and destination paths with `realpath()` and restrict file mutations, including direct tools and undo/redo, to the configured `Incoming` and `Sorted` directories. Reject an unsafe plan before its first mutation.

---

## ⚙️ Phase A: Core Control & API Management
*Goal: Give the user absolute control over which AI does what, and make the system resilient to rate limits.*

- [x] **Agent Assignment (Role Binding):**
  - **DB:** Add `assigned_agent` column (TEXT) to the `providers` table in `core/database.py`.
  - **UI:** Add a dropdown in the API Hub (`gui/settings_tab.py`) with options: `Cortex`, `Foldy`, `Syntax`, `Scout`, `Any`.
  - **Router:** Filter providers in `core/router.py` based on the `agent_name` passed to `route_request()`.
- [x] **Multiple API Key Load Balancing:**
  - **Router:** If a provider returns a `429 Rate Limit`, `core/router.py` will look for another key associated with the same provider in the DB, update the `usage_ledger`, and automatically retry the request.
- [x] **Provider Fallback Visualization:**
  - **UI:** When a provider fails, flash its card red in the `gui/live_feed.py`. Flash the backup provider green when it takes over.
- [x] **Explicit Shared-Credential Rotation:**
  - **Safety:** Rotation targets one selected credential ID, validates the normalized endpoint and provider links, and rolls back failed updates without changing provider assignments.
- [x] **Provider Auto-Discovery:**
  - **Backend:** `core/discovery.py` fetches and filters OpenRouter free models and upserts missing disabled providers without replacing existing rows.
  - **Scope:** Discovery is user-triggered from the API Hub rather than an autonomous background catalog refresh.
- [x] **Persistent State Outside the Repository:**
  - **Storage:** Database, Fernet key, and operation log use `%APPDATA%\STEWARD`; legacy root files are copied, never moved or overwritten.

---

## 🎨 Phase B: The Cyber-Kawaii Experience
*Goal: Turn the UI into a living, breathing animation that visually explains what the AIs are doing.*

- [x] **Dynamic Chat Bubble States:**
  - **UI:** `gui/chat_tab.py` supports dynamic `THINKING`, `TOOL_USE`, `STREAMING`, `DONE`, and `ERROR` states.
- [x] **Visual Agent Communication (Handoffs):**
  - **UI:** `gui/chat_tab.py` renders the handoff arc and agent-state feedback through the Live Feed.
  - **Scope:** This covers the implemented handoff visualization, not an autonomous multi-agent planner.
- [x] **Live Constellation View:**
  - **UI:** `gui/constellation_view.py` provides a responsive node-link diagram whose agent nodes animate while working.
- [x] **Smooth Page Transitions:**
  - **UI:** `gui/main_window.py` fades the active tab content in on navigation.
- [x] **Execution Success Pulse:**
  - **UI:** Successful Organizer execution pulses the execute button green.

---

## 🧠 Phase C: The Swarm & Code Intelligence
*Goal: Make STEWARD an autonomous coding beast that rivals Cline.*

- [x] **Bounded Specialist Delegation:**
  - **Architecture:** `Cortex` (Supervisor) parses a validated, eight-task-max breakdown and delegates it to registered specialist workers.
  - **Specialists:** Foldy handles dry-run file previews, Scout performs RAG search, and Syntax provides provider-backed text-only coding assistance; Click remains future work.
  - **Reliability:** Results are synthesized by Cortex, specialist failures are isolated, and delegation start/completion is visible in the Live Feed.
- [x] **Provider-Backed Text-Only Syntax:**
  - **Agent:** `CodingAgent` performs generation, debugging, refactoring, review, and explanation through the shared router with `agent_name="Syntax"`, `require_tools=False`, and no tool definitions.
  - **Boundary:** Syntax has no filesystem or process-execution surface and never applies generated code.
- [x] **Bounded Cortex Conversation Memory:**
  - **Memory:** General chat keeps at most 6 turns, 12,000 total characters, and 4,000 characters per message in memory.
  - **Invalidation:** Clearing chat erases history, invalidates pending or in-flight file previews, and rejects stale responses and specialist UI continuations.
- [x] **Meta-Prompting (Architect + Builder):**
  - **Router:** `Cortex` uses a heavy reasoning model (e.g., Kimi) to write a strict JSON blueprint, published as an immutable app-owned artifact.
  - **Review:** The GUI's explicit Plan first mode accepts only validated `CODING` routing and requires approval bound to the plan UUID before a separate text-only Syntax request.
  - **Implementation:** Commit `1c66ecb9`; confirmed pushed as an ancestor of `origin/main`.
  - **Scope:** Architect and builder remain text-only; automated application of the blueprint remains Phase C3.
- [x] **AST Parsing & JSON Patches (C3-I1 through C3-I3):**
  - **Staging:** A pure one-file AST/byte-preserving engine validates strict artifacts, resolves definition anchors, and produces deterministic exact diffs.
  - **Mutation:** A separate admitted workspace layer revalidates proofs and source identity, journals intent/completion, and supports hash-guarded undo/redo for one selected `.py` file.
  - **Review/UI:** The Chat header's **Patch Review** workflow selects the workspace and target, persists an immutable artifact, and requires a distinct epoch-bound, single-use approval before guarded apply.
  - **Implementation:** Commits `6c9017ed` and `0da71eda`; local and not pushed by this change.
  - **Boundary:** Syntax remains text-only; C3 never executes, imports, lints, or tests the target. Multi-file patches and self-healing remain future work.
- [ ] **Self-Healing Loop & Linter Integration:**
  - **Future execution worker:** A separately sandboxed worker will own lint/run/edit cycles with hard iteration bounds; current `Syntax` cannot execute code or edit files.
- [x] **Persistent Document RAG (Scout):**
  - **Memory:** `Scout` uses persistent ChromaDB ingestion and semantic retrieval over indexed documents with bounded results and source citations.
- [x] **Codebase-scale Semantic Context (symbol retrieval):**
  - **Memory:** A separate persistent `steward_code` collection indexes an explicitly selected project root with bounded, read-only symbol chunks and supplies path/line-aware context to Syntax.
  - **Safety:** Indexing denies secrets and dependency caches, refuses a selected root whose own basename is in `DENIED_DIRECTORIES`, refuses escaping symlinks/junctions, enforces file/byte limits, and never executes or modifies source.
  - **Implementation:** Commit `8e8d4f34`; confirmed pushed as an ancestor of `origin/main`.
- [x] **Dependency-graph Context (Phase C7):**
  - **Memory:** Static Python import/call edges are derived during the existing bounded admission read, persisted as identifier-only scalar metadata, traversed with deterministic bounds, and used to expand root-scoped semantic context across files.
  - **Safety:** Graph resolution never imports or executes source, resolves only against admitted root inventory, records external/unresolved imports without reading them, and cannot cross roots or expose denied paths. Provider limits remain five snippets, 2,000 characters per snippet, and 8,000 total characters including headers.
  - **Implementation:** Commit `883347bf`; local and not pushed by this change.
  - **Limitations:** Resolution is a static name-based approximation: dynamic imports, aliases, ambiguous symbols, and runtime dependency behavior are not resolved.

---

## 🔬 Phase D: Research-Backed Horizon
*Goal: Bleeding-edge features that turn STEWARD into an enterprise-grade desktop assistant.*

- [ ] **MCP (Model Context Protocol) Support:** Connect STEWARD to databases, web browsers, and third-party SaaS apps using Anthropic's open standard.
- [x] **Scheduled Agents:** A background scheduler (using the `schedule` library) runs recurring file scans from the Organizer tab at 15-minute, 30-minute, 1-hour, or 6-hour intervals. Preferences and last-run state persist in AppData, the real categorization/move path is used, cancellation is checked between file operations, and restart creates an isolated generation whose old worker cannot commit state or notifications into the replacement.

## Removed from scope
These historical declarations are not active roadmap work and no corresponding running capability is present. Their original titles and descriptions are preserved for the decision record.

- **Screen-Aware Automation** (PLAN D2; historical declaration: `Click` (PC Agent) will use a vision model to analyze a screenshot and propose an action; ambiguous actions must be refused and no PC-control surface exists today). **DEFERRED — REMOVED FROM DECLARED SCOPE.** Rationale: Screen-aware automation / PC control grants synthetic keyboard and mouse input across the ENTIRE desktop, not confined to Incoming/Sorted or the admitted code workspace. Unlike file operations, input has no path, so it cannot be contained by path admission or realpath rules at all. A single model error or hostile provider response could interact with any application, including credential dialogs, browsers, or system settings. This is a strictly larger blast radius than C3's admitted one-file byte replacement, with no equivalent containment mechanism.
- **Voice Activation** (PLAN D4; historical declaration: `pyaudio` + `whisper` integration for hands-free wake-word control). **DEFERRED — REMOVED FROM DECLARED SCOPE.** Rationale: Voice control requires audio capture (a new privacy surface) plus STT/TTS dependencies (a new trust surface) to duplicate a capability already served by text chat. The C4-ISO host findings also recorded only 568–885 MB available physical memory on an 8 GB host, making model-bearing audio features impractical here independent of the security case.
- **Phone Remote Control** (PLAN D5; historical declaration: a lightweight authenticated `FastAPI` server that lets you control your desktop STEWARD from your phone over Wi-Fi, with all remote actions sandboxed and logged). **DEFERRED — REMOVED FROM DECLARED SCOPE.** Rationale: Phone / remote control requires a network-reachable authenticated control plane. STEWARD already holds filesystem mutation authority (C3) and provider credentials. Exposing that authority to a network endpoint multiplies blast radius: one authentication flaw becomes remote file mutation and credential access. Disproportionate to the convenience for a local desktop tool.

Common thread: each grants authority beyond the application's existing bounded mutation boundary, with no proportionate benefit for a local desktop tool. These decisions follow the same discipline as C4-R and C4-ISO, which deferred execution rather than claim a boundary that could not be proven.

---
*Created with ❤️ by Elijah Rei Z. Bicomong*
