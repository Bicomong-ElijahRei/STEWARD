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
- **v3.0 — Advanced Code Intelligence & Phase D (Future):** surgical code workflows,
  self-healing loops, and research-backed integrations such
  as MCP, voice, and remote control.

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
  - **Implementation:** Local commit `1c66ecb9`; not pushed by this change.
  - **Scope:** Architect and builder remain text-only; automated application of the blueprint remains Phase C3.
- [ ] **AST Parsing & JSON Patches:**
  - **Future mutation worker:** A separate reviewed component will parse code and apply surgical patches to an approved plan; current `Syntax` remains text-only and cannot mutate files.
- [ ] **Self-Healing Loop & Linter Integration:**
  - **Future execution worker:** A separately sandboxed worker will own lint/run/edit cycles with hard iteration bounds; current `Syntax` cannot execute code or edit files.
- [x] **Persistent Document RAG (Scout):**
  - **Memory:** `Scout` uses persistent ChromaDB ingestion and semantic retrieval over indexed documents with bounded results and source citations.
- [x] **Codebase-scale Semantic Context (symbol retrieval):**
  - **Memory:** A separate persistent `steward_code` collection indexes an explicitly selected project root with bounded, read-only symbol chunks and supplies path/line-aware context to Syntax.
  - **Safety:** Indexing denies secrets and dependency caches, refuses a selected root whose own basename is in `DENIED_DIRECTORIES`, refuses escaping symlinks/junctions, enforces file/byte limits, and never executes or modifies source.
  - **Implementation:** Local commit `8e8d4f34`; not pushed by this change.
- [ ] **Dependency-graph Context:**
  - **Memory:** Model imports and calls to expand or rerank repository-wide context. This remains explicit Phase C7 backlog rather than an implied feature of symbol retrieval.

---

## 🔬 Phase D: Research-Backed Horizon
*Goal: Bleeding-edge features that turn STEWARD into an enterprise-grade desktop assistant.*

- [ ] **MCP (Model Context Protocol) Support:** Connect STEWARD to databases, web browsers, and third-party SaaS apps using Anthropic's open standard.
- [ ] **Screen-Aware Automation:** `Click` (PC Agent) will use a vision model to analyze a screenshot and propose an action; ambiguous actions must be refused and no PC-control surface exists today.
- [x] **Scheduled Agents:** A background scheduler (using the `schedule` library) runs recurring file scans from the Organizer tab at 15-minute, 30-minute, 1-hour, or 6-hour intervals. Preferences and last-run state persist in AppData, the real categorization/move path is used, cancellation is checked between file operations, and restart creates an isolated generation whose old worker cannot commit state or notifications into the replacement.
- [ ] **Voice Activation:** `pyaudio` + `whisper` integration for hands-free wake-word control.
- [ ] **Phone Remote Control:** A lightweight authenticated `FastAPI` server that lets you control your desktop STEWARD from your phone over Wi-Fi, with all remote actions sandboxed and logged.

---
*Created with ❤️ by Elijah Rei Z. Bicomong*
