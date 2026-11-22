# 🗺️ STEWARD v2: The Master Blueprint

> **Vision:** To evolve STEWARD from a basic file organizer into an enterprise-grade, autonomous Multi-Agent system with a visually stunning "Cyber-Kawaii" interface.

This document serves as the official technical roadmap for STEWARD v2. It outlines the architectural upgrades, UI/UX overhauls, and safety mechanisms required to make STEWARD a state-of-the-art desktop AI assistant.

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
- **v2.4 — Hierarchical Swarm & Scheduling (Current):** readable plain-text Markdown
  chat rendering, Cortex-to-specialist delegation with bounded workers, failure
  isolation, and Live Feed observability, plus restart-persistent recurring file scans.
- **v3.0 — Advanced Code Intelligence & Phase D (Future):** meta-prompting,
  surgical code workflows, self-healing loops, and research-backed integrations such
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
- [ ] **Provider Auto-Discovery:**
  - **Backend:** Finalize the OpenRouter zero-prompt-cost scraper in `core/discovery.py` so it automatically populates the SQLite DB with new free models.

---

## 🎨 Phase B: The Cyber-Kawaii Experience
*Goal: Turn the UI into a living, breathing animation that visually explains what the AIs are doing.*

- [ ] **4-State Chat Bubbles:**
  - **UI:** Update `gui/chat_tab.py` to support dynamic states: `THINKING` (Pulsing shimmer), `TOOL_USE` (Spinning gear icon), `STREAMING` (Typewriter text effect), and `DONE` (Subtle green checkmark).
- [ ] **Visual Agent Communication (Handoffs):**
  - **UI:** In `gui/live_feed.py`, use a Tkinter Canvas to draw animated glowing arcs/light beams between agent avatars when a task is handed off.
  - **UI:** Add cute speech bubbles (e.g., *"Cortex: Routing to Foldy..."*).
- [ ] **Live Constellation View:**
  - **UI:** Add a node-link diagram in the sidebar showing the swarm. Nodes light up as they work, visualizing the brain's workflow.
- [ ] **Smooth Page Transitions:**
  - **UI:** Implement custom Canvas animations or `ctk-transitions` for sliding/fading tabs in `gui/main_window.py`.
- [ ] **File Materialize Animation:**
  - **UI:** When a file is moved, play a glowing tile animation that drops into the destination folder icon.

---

## 🧠 Phase C: The Swarm & Code Intelligence
*Goal: Make STEWARD an autonomous coding beast that rivals Cline.*

- [x] **Hierarchical Agent Swarm (Brain → Managers → Workers):**
  - **Architecture:** `Cortex` (Supervisor) parses a validated, eight-task-max breakdown and delegates it to registered specialist workers.
  - **Specialists:** Foldy handles dry-run file previews, Scout performs RAG search, and Click/Syntax have provider-backed fallbacks.
  - **Reliability:** Results are synthesized by Cortex, specialist failures are isolated, and delegation start/completion is visible in the Live Feed.
- [ ] **Meta-Prompting (Architect + Builder):**
  - **Router:** `Cortex` uses a heavy reasoning model (e.g., Kimi) to write a strict JSON blueprint. `Syntax` uses a fast model to execute the blueprint.
- [ ] **AST Parsing & JSON Patches:**
  - **Syntax Agent:** Instead of rewriting entire files, `agents/coding_agent.py` will use Python's `ast` module to parse the code and apply surgical "find and replace" JSON patches.
- [ ] **Self-Healing Loop & Linter Integration:**
  - **Execution:** `Syntax` writes code → runs `flake8` (linter) → auto-fixes errors → runs `python script.py` in a `subprocess`.
  - **Error Handling:** If the code crashes, `Syntax` reads the `stderr` traceback and attempts to fix the bug autonomously.
- [ ] **RAG-based Infinite Context:**
  - **Memory:** `Syntax` uses `ChromaDB` to semantic-search the entire codebase. It pulls only the relevant functions into its 128K context window, allowing it to work on massive projects.

---

## 🔬 Phase D: Research-Backed Horizon
*Goal: Bleeding-edge features that turn STEWARD into an enterprise-grade desktop assistant.*

- [ ] **MCP (Model Context Protocol) Support:** Connect STEWARD to databases, web browsers, and third-party SaaS apps using Anthropic's open standard.
- [ ] **Screen-Aware Automation:** `Click` (PC Agent) uses `llama3.2-vision` to take a screenshot, analyze the UI, and decide where to click.
- [x] **Scheduled Agents:** A background scheduler (using the `schedule` library) runs recurring file scans from the Organizer tab at 15-minute, 30-minute, 1-hour, or 6-hour intervals. Preferences and last-run state persist in AppData, the real categorization/move path is used, and shutdown cancels the worker cleanly.
- [ ] **Voice Activation:** `pyaudio` + `whisper` integration for hands-free wake-word control.
- [ ] **Phone Remote Control:** A lightweight `FastAPI` server that lets you control your desktop STEWARD from your phone over Wi-Fi.

---
*Created with ❤️ by Elijah Rei Z. Bicomong*