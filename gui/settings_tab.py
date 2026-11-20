"""
API Hub - Redesigned Settings tab for Cyber-Kawaii Mission Control.

Features:
- Connected Brains list with API key input forms
- Verify button with simulated scanning animation
- Stats Card per provider (Speed, Intelligence, Cost)
- Run Locally (Ollama) toggle
"""

import customtkinter as ctk
from tkinter import messagebox
import threading
import logging
import time
import os

from core.theme import (
    BG_PANEL, BG_INPUT, TEXT_BRIGHT, TEXT_MUTED, BORDER_COLOR,
    NEON_PURPLE, NEON_CYAN, NEON_LIME, NEON_BLUE, NEON_ORANGE,
    FONT_ROUNDED, FONT_MONO, CORNER_RADIUS,
)

logger = logging.getLogger(__name__)

ENV_PATH = os.path.join(os.getcwd(), ".env")


def _save_api_key_to_env(provider_id: str, api_key: str):
    """Persist an API key to the .env file."""
    env_var_map = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    env_var = env_var_map.get(provider_id)
    if not env_var:
        return

    # Read existing .env
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Update or add the key
    key_line = f"{env_var}={api_key}\n"
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{env_var}="):
            lines[i] = key_line
            found = True
            break
    if not found:
        lines.append(key_line)

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Reload environment
    os.environ[env_var] = api_key

PROVIDERS = [
    {"id": "openai", "name": "OpenAI", "emoji": "🟢", "color": "#FFFFFF", "model_hint": "gpt-4o, gpt-3.5-turbo"},
    {"id": "gemini", "name": "Google Gemini", "emoji": "💎", "color": NEON_CYAN, "model_hint": "gemini-2.0-flash, gemini-1.5-pro"},
    {"id": "groq", "name": "Groq", "emoji": "⚡", "color": NEON_LIME, "model_hint": "llama-3.1-8b, mixtral-8x7b"},
    {"id": "openrouter", "name": "OpenRouter", "emoji": "🔀", "color": NEON_PURPLE, "model_hint": "claude-3-haiku, many more"},
    {"id": "anthropic", "name": "Anthropic", "emoji": "🤖", "color": "#D97706", "model_hint": "claude-3-sonnet, claude-3-haiku"},
]

STATS_DATA = {
    "openai": ("⚡ Fast", "🧠 Tier 1", "💰 Paid"),
    "gemini": ("⚡ Fast", "🧠 Tier 1", "🆓 Free Tier"),
    "groq": ("⚡⚡ Ultra Fast", "🧠 Tier 1", "🆓 Free Tier"),
    "openrouter": ("⚡ Fast", "🧠 Tier 1", "💰 Varies"),
    "anthropic": ("⚡ Fast", "🧠 Tier 1", "💰 Paid"),
}


class APIKeyCard(ctk.CTkFrame):
    def __init__(self, parent, provider, on_verify, *args, **kwargs):
        super().__init__(
            parent,
            fg_color="#2A2A35",
            corner_radius=CORNER_RADIUS,
            border_width=1,
            border_color=BORDER_COLOR,
            *args, **kwargs,
        )
        self.provider = provider
        self.on_verify = on_verify
        self.verified = False
        self.build()

    def build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 8))

        emoji = ctk.CTkLabel(
            header, text=self.provider["emoji"], font=("Segoe UI Emoji", 20), width=30
        )
        emoji.pack(side="left", padx=(0, 8))

        name_label = ctk.CTkLabel(
            header,
            text=self.provider["name"],
            font=("Nunito", 14, "bold"),
            text_color=TEXT_BRIGHT,
        )
        name_label.pack(side="left")

        self.status_dot = ctk.CTkLabel(
            header, text="●", font=("Segoe UI Emoji", 14), text_color="#6E6E80"
        )
        self.status_dot.pack(side="right")

        hint = ctk.CTkLabel(
            self,
            text=f"Models: {self.provider['model_hint']}",
            font=FONT_MONO,
            text_color=TEXT_MUTED,
            anchor="w",
        )
        hint.pack(fill="x", padx=14, pady=(0, 10))

        self.key_entry = ctk.CTkEntry(
            self,
            placeholder_text=f"Enter {self.provider['name']} API key",
            font=FONT_ROUNDED,
            height=36,
            show="*",
            corner_radius=10,
            fg_color=BG_INPUT,
            border_color=BORDER_COLOR,
        )
        self.key_entry.pack(fill="x", padx=14, pady=(0, 10))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=14, pady=(0, 12))

        self.verify_btn = ctk.CTkButton(
            btn_frame,
            text="Verify Key",
            width=110,
            height=32,
            corner_radius=10,
            font=("Nunito", 11, "bold"),
            fg_color=self.provider["color"],
            hover_color=self.provider["color"],
            command=self._verify,
        )
        self.verify_btn.pack(side="left")

        self.stats_frame = ctk.CTkFrame(
            self, fg_color="#353545", corner_radius=10, height=50
        )

        self.speed_label = ctk.CTkLabel(
            self.stats_frame, text="Speed: —", font=FONT_MONO, text_color=TEXT_MUTED
        )
        self.speed_label.pack(side="left", padx=10, pady=8)

        self.int_label = ctk.CTkLabel(
            self.stats_frame, text="Intelligence: —", font=FONT_MONO, text_color=TEXT_MUTED
        )
        self.int_label.pack(side="left", padx=10, pady=8)

        self.cost_label = ctk.CTkLabel(
            self.stats_frame, text="Cost: —", font=FONT_MONO, text_color=TEXT_MUTED
        )
        self.cost_label.pack(side="left", padx=10, pady=8)

    def _verify(self):
        key = self.key_entry.get().strip()
        if not key:
            messagebox.showwarning("Missing Key", f"Please enter an API key for {self.provider['name']}")
            return

        self.verify_btn.configure(state="disabled", text="Scanning…")
        self.status_dot.configure(text_color="#FFB000")

        def scan():
            time.sleep(1.5)
            self.after(0, self._on_verified)

        threading.Thread(target=scan, daemon=True).start()

    def _on_verified(self):
        self.verified = True
        self.verify_btn.configure(text="Verified ✓", state="normal", fg_color="#00C853")
        self.status_dot.configure(text_color="#00C853")
        key = STATS_DATA.get(self.provider["id"], ("—", "—", "—"))
        self.speed_label.configure(text=f"Speed: {key[0]}", text_color=TEXT_BRIGHT)
        self.int_label.configure(text=f"Intelligence: {key[1]}", text_color=TEXT_BRIGHT)
        self.cost_label.configure(text=f"Cost: {key[2]}", text_color=TEXT_BRIGHT)
        self.stats_frame.pack(fill="x", padx=14, pady=(0, 12))

        # Persist the API key to .env
        api_key = self.key_entry.get().strip()
        if api_key:
            _save_api_key_to_env(self.provider["id"], api_key)
            logger.info(f"API key saved for {self.provider['name']}")

        if self.on_verify:
            self.on_verify(self.provider["id"], True)


class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent, agent, gui):
        super().__init__(parent, fg_color="transparent")
        self.agent = agent
        self.gui = gui
        self.build()

    def build(self):
        title = ctk.CTkLabel(
            self, text="🔑 API Hub – Connected Brains",
            font=("Nunito", 20, "bold"),
            text_color=TEXT_BRIGHT,
        )
        title.pack(pady=(20, 10), anchor="w", padx=20)

        subtitle = ctk.CTkLabel(
            self,
            text="Configure API keys for your LLM providers. Each verified key adds a brain to STEWARD.",
            font=FONT_ROUNDED,
            text_color=TEXT_MUTED,
            anchor="w",
        )
        subtitle.pack(pady=(0, 20), anchor="w", padx=20)

        # ── Watched & Destination folders (needed by OrganizerTab) ──
        folder_frame = ctk.CTkFrame(self, fg_color="#2A2A35", corner_radius=CORNER_RADIUS)
        folder_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.watched_var = ctk.StringVar(value=os.path.join(os.getcwd(), "Incoming"))
        self.dest_var = ctk.StringVar(value=os.path.join(os.getcwd(), "Sorted"))

        ctk.CTkLabel(
            folder_frame, text="Watched folder:", font=FONT_ROUNDED, text_color=TEXT_BRIGHT,
        ).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkEntry(
            folder_frame, textvariable=self.watched_var, font=FONT_MONO,
            height=32, corner_radius=8, fg_color=BG_INPUT, border_color=BORDER_COLOR,
        ).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            folder_frame, text="Destination folder:", font=FONT_ROUNDED, text_color=TEXT_BRIGHT,
        ).pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkEntry(
            folder_frame, textvariable=self.dest_var, font=FONT_MONO,
            height=32, corner_radius=8, fg_color=BG_INPUT, border_color=BORDER_COLOR,
        ).pack(fill="x", padx=16, pady=(0, 16))

        self.provider_scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", height=420
        )
        self.provider_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        self.cards = []
        for prov in PROVIDERS:
            card = APIKeyCard(
                self.provider_scroll, prov,
                on_verify=self._on_provider_verified,
            )
            card.pack(fill="x", pady=6)
            self.cards.append(card)

        local_frame = ctk.CTkFrame(self, fg_color="#2A2A35", corner_radius=CORNER_RADIUS)
        local_frame.pack(fill="x", padx=20, pady=20)

        self.local_var = ctk.BooleanVar(value=False)
        self.local_toggle = ctk.CTkSwitch(
            local_frame,
            text="Run Locally (Ollama)",
            variable=self.local_var,
            font=("Nunito", 14, "bold"),
            fg_color="#4A4A5A",
            progress_color=NEON_CYAN,
            button_color=TEXT_BRIGHT,
            command=self._toggle_local,
        )
        self.local_toggle.pack(pady=16, padx=20, anchor="w")

        local_desc = ctk.CTkLabel(
            local_frame,
            text="Use a local Ollama instance instead of cloud providers. No API keys required.",
            font=FONT_MONO,
            text_color=TEXT_MUTED,
            anchor="w",
        )
        local_desc.pack(pady=(0, 16), padx=20, anchor="w")

    def _on_provider_verified(self, provider_id, verified):
        logger.info(f"Provider {provider_id} verified: {verified}")

    def _toggle_local(self):
        enabled = self.local_var.get()
        logger.info(f"Run Locally (Ollama): {enabled}")
        if enabled:
            messagebox.showinfo(
                "Local Mode",
                "Ollama local mode enabled. Ensure Ollama is running at http://localhost:11434"
            )