"""
LiveFeedWidget - Real-time agent activity timeline for Mission Control.

Displays cards showing which agent is active, with loading bars and status text.
Receives events via callbacks from SupervisorAgent and FileAgent.
"""

import customtkinter as ctk
from core.theme import (
    BG_PANEL, TEXT_BRIGHT, TEXT_MUTED, BORDER_COLOR, CORNER_RADIUS,
    AGENT_COLORS,
)
from agents.agent_config import AGENT_CONFIG
from gui.constellation_view import ConstellationView


class LiveFeedWidget(ctk.CTkScrollableFrame):
    """A scrollable feed of agent activity cards."""

    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            fg_color=BG_PANEL,
            corner_radius=CORNER_RADIUS,
            border_width=1,
            border_color=BORDER_COLOR,
            **kwargs,
        )
        self.cards = []
        self._max_cards = 50

        self.constellation_view = ConstellationView(self)
        self.constellation_view.pack(fill="x", padx=4, pady=(4, 10))

    def add_event(self, agent_name: str, status: str, progress: float = 0.0,
                  detail: str = ""):
        """
        Add a new activity card to the feed.

        Args:
            agent_name: Name of the agent (e.g., "Cortex", "Foldy")
            status: Human-readable status text
            progress: 0.0 to 1.0 for loading bar (0 = hidden)
            detail: Optional extra detail text
        """
        config = AGENT_CONFIG.get(agent_name, {})
        color = config.get("color", TEXT_MUTED)
        emoji = config.get("emoji", "✨")
        role = config.get("role", "Agent")

        card = ctk.CTkFrame(self, fg_color="#2A2A35", corner_radius=10)
        card.pack(fill="x", padx=8, pady=4)

        # Agent avatar + name row
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))

        avatar = ctk.CTkLabel(
            header, text=emoji, font=("Segoe UI Emoji", 18), width=30
        )
        avatar.pack(side="left", padx=(0, 8))

        name_label = ctk.CTkLabel(
            header,
            text=f"{agent_name}  •  {role}",
            font=("Nunito", 12, "bold"),
            text_color=color,
        )
        name_label.pack(side="left")

        # Status text
        status_label = ctk.CTkLabel(
            card,
            text=status,
            font=("Nunito", 11),
            text_color=TEXT_BRIGHT,
            anchor="w",
        )
        status_label.pack(fill="x", padx=10, pady=(2, 2))

        # Detail (optional)
        if detail:
            detail_label = ctk.CTkLabel(
                card,
                text=detail,
                font=("Consolas", 9),
                text_color=TEXT_MUTED,
                anchor="w",
            )
            detail_label.pack(fill="x", padx=10, pady=(0, 4))

        # Loading bar (only if progress > 0)
        if progress > 0:
            bar_frame = ctk.CTkFrame(card, fg_color="transparent", height=6)
            bar_frame.pack(fill="x", padx=10, pady=(0, 8))
            bar_frame.pack_propagate(False)

            bg_bar = ctk.CTkFrame(bar_frame, fg_color="#3A3A4A", corner_radius=3)
            bg_bar.pack(fill="both", expand=True)

            fill_bar = ctk.CTkFrame(bg_bar, fg_color=color, corner_radius=3, width=0)
            fill_bar.place(relx=0, rely=0, relheight=1, relwidth=progress)

        self.cards.append(card)

        # Limit number of cards
        if len(self.cards) > self._max_cards:
            oldest = self.cards.pop(0)
            oldest.destroy()

        # Auto-scroll to bottom
        self.after_idle(self._scroll_to_bottom)
        return card

    def provider_failover(self, failed_provider: str, fallback_provider: str):
        """Flash the failed provider red and its successful backup green."""
        events = (
            (
                failed_provider,
                "Provider failed",
                f"Falling back to {fallback_provider}",
                "#B91C1C",
            ),
            (
                fallback_provider,
                "Backup provider active",
                f"Took over from {failed_provider}",
                "#15803D",
            ),
        )
        for provider, status, detail, flash_color in events:
            card = self.add_event(provider, status, detail=detail)
            card.configure(fg_color=flash_color)
            self.after(1200, lambda card=card: self._restore_card_color(card))

    @staticmethod
    def _restore_card_color(card):
        """Restore a flash card if it has not been cleared or destroyed."""
        try:
            if card.winfo_exists():
                card.configure(fg_color="#2A2A35")
        except Exception:
            # Tkinter raises when a delayed callback references a destroyed card.
            pass

    def _scroll_to_bottom(self):
        try:
            self._parent_canvas.yview_moveto(1.0)
        except AttributeError:
            pass

    def clear(self):
        for card in self.cards:
            card.destroy()
        self.cards.clear()

    def agent_working(self, agent_name: str, detail: str = ""):
        """Convenience: show an agent is actively working."""
        config = AGENT_CONFIG.get(agent_name, {})
        status = config.get("status_working", "Working…")
        self.add_event(agent_name, status, progress=0.5, detail=detail)
        self.constellation_view.update_state(agent_name, "WORKING")

    def agent_done(self, agent_name: str, detail: str = ""):
        """Convenience: show an agent completed its task."""
        config = AGENT_CONFIG.get(agent_name, {})
        status = config.get("status_done", "Done.")
        self.add_event(agent_name, status, progress=1.0, detail=detail)
        self.constellation_view.update_state(agent_name, "DONE")

    def agent_idle(self, agent_name: str):
        """Convenience: show an agent is idle."""
        config = AGENT_CONFIG.get(agent_name, {})
        status = config.get("status_idle", "Idle.")
        self.add_event(agent_name, status, progress=0.0)
        self.constellation_view.update_state(agent_name, "IDLE")