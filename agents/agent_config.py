"""
STEWARD Agent Personas & Avatars - Cyber-Kawaii Mission Control

Each agent has a name, role, color, emoji avatar, and personality description.
Used by the LiveFeedWidget and AgentAvatar UI components.
"""

from core.theme import NEON_PURPLE, NEON_CYAN, NEON_LIME, NEON_BLUE, NEON_ORANGE

AGENT_CONFIG = {
    "Cortex": {
        "role": "Supervisor / Router",
        "color": NEON_PURPLE,
        "emoji": "🧠",
        "description": "Routes tasks to the right specialist agent.",
        "status_idle": "Standing by…",
        "status_working": "Analyzing your request…",
        "status_done": "Routing complete.",
    },
    "Foldy": {
        "role": "File Operations",
        "color": NEON_CYAN,
        "emoji": "📁",
        "description": "Handles move, rename, delete, organize, undo/redo.",
        "status_idle": "File system quiet.",
        "status_working": "Scanning and organizing files…",
        "status_done": "File operations complete.",
    },
    "Click": {
        "role": "PC Control",
        "color": NEON_LIME,
        "emoji": "🖱️",
        "description": "Desktop automation, mouse, keyboard, app launching.",
        "status_idle": "Hands off the keyboard.",
        "status_working": "Controlling the PC…",
        "status_done": "PC action executed.",
    },
    "Scout": {
        "role": "Browser / RAG",
        "color": NEON_BLUE,
        "emoji": "🔍",
        "description": "Semantic search over documents and knowledge base.",
        "status_idle": "Indexing knowledge…",
        "status_working": "Searching the archives…",
        "status_done": "Search complete.",
    },
    "Syntax": {
        "role": "Coding",
        "color": NEON_ORANGE,
        "emoji": "💻",
        "description": "Code generation, debugging, refactoring.",
        "status_idle": "Editor ready.",
        "status_working": "Writing code…",
        "status_done": "Code generated.",
    },
}

AGENT_ROUTING_KEYS = {
    "FILE_OP": "Foldy",
    "PC_CONTROL": "Click",
    "RAG": "Scout",
    "CODING": "Syntax",
    "GENERAL_CHAT": "Cortex",
    "UNKNOWN": "Cortex",
}