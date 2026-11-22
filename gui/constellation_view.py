"""Live node-link view of the STEWARD agent swarm."""

import customtkinter as ctk

from core.theme import (
    BORDER_COLOR,
    NEON_BLUE,
    NEON_CYAN,
    NEON_LIME,
    NEON_ORANGE,
    NEON_PURPLE,
    TEXT_BRIGHT,
)
from gui.anim import SafeTick, lerp_color


AGENT_COLORS = {
    "Cortex": NEON_PURPLE,
    "Foldy": NEON_CYAN,
    "Click": NEON_LIME,
    "Scout": NEON_BLUE,
    "Syntax": NEON_ORANGE,
}

# Normalized positions keep the layout stable at every canvas size. The
# horizontal and vertical axes are scaled separately so the constellation
# always fills the available panel without distorting its ordering.
AGENT_POSITIONS = {
    "Cortex": (0.50, 0.50),
    "Foldy": (0.50, 0.15),
    "Click": (0.85, 0.50),
    "Scout": (0.50, 0.85),
    "Syntax": (0.15, 0.50),
}
RELATIVE_RADIUS = 0.35

IDLE_COLOR = "#555555"
DONE_COLOR = "#15803D"
PULSE_INTERVAL_MS = 50
DONE_HOLD_MS = 2000
DONE_FADE_MS = 500


class ConstellationView(ctk.CTkCanvas):
    """Responsive diagram showing the current state of each swarm agent."""

    def __init__(self, parent, **kwargs):
        kwargs.setdefault("width", 280)
        kwargs.setdefault("height", 220)
        kwargs.setdefault("bg", "#2A2A35")
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, **kwargs)

        self.nodes = {}
        self.labels = {}
        self.edges = {}
        self._states = {name: "IDLE" for name in AGENT_COLORS}
        self._colors = {name: IDLE_COLOR for name in AGENT_COLORS}
        self._ticks = {}
        self._destroyed = False

        self.bind("<Configure>", self._on_resize)
        self._draw_graph(*self._canvas_dimensions())

    def _canvas_dimensions(self):
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1:
            width = int(self.cget("width"))
        if height <= 1:
            height = int(self.cget("height"))
        return max(1, width), max(1, height)

    def _draw_graph(self, width, height):
        """Redraw all geometry and restore each node's current color."""
        self.delete("all")
        self.nodes.clear()
        self.labels.clear()
        self.edges.clear()

        # Scale each axis independently so wide panels are actually used.
        # Reserve vertical room below the lower node for its label on short
        # canvases; otherwise the "Scout" label can be clipped at the edge.
        radius_x = width * 0.5
        node_radius = max(10, min(18, min(radius_x, height) * 0.16))
        max_radius_y = max(
            0,
            (height / 2 - node_radius - 12 - 8) / 0.7,
        )
        radius_y = min(height * 0.4, max_radius_y)
        positions = {
            agent_name: (
                width / 2 + (relative_x - 0.5) * 2 * radius_x,
                height / 2 + (relative_y - 0.5) * 2 * radius_y,
            )
            for agent_name, (relative_x, relative_y) in AGENT_POSITIONS.items()
        }

        cortex_x, cortex_y = positions["Cortex"]
        for agent_name in AGENT_POSITIONS:
            if agent_name == "Cortex":
                continue
            agent_x, agent_y = positions[agent_name]
            self.edges[agent_name] = self.create_line(
                cortex_x,
                cortex_y,
                agent_x,
                agent_y,
                fill=BORDER_COLOR,
                width=2,
            )

        for agent_name, (agent_x, agent_y) in positions.items():
            color = self._colors.get(agent_name, IDLE_COLOR)
            self.nodes[agent_name] = self.create_oval(
                agent_x - node_radius,
                agent_y - node_radius,
                agent_x + node_radius,
                agent_y + node_radius,
                fill=color,
                outline=TEXT_BRIGHT,
                width=1,
            )
            self.labels[agent_name] = self.create_text(
                agent_x,
                agent_y + node_radius + 12,
                text=agent_name,
                fill=TEXT_BRIGHT,
                font=("Nunito", 9, "bold"),
            )

    def _on_resize(self, event):
        """Recalculate absolute positions from the resized canvas bounds."""
        if self._destroyed:
            return
        width = max(1, int(event.width))
        height = max(1, int(event.height))
        self._draw_graph(width, height)

    def _set_node_color(self, agent_name, color):
        self._colors[agent_name] = color
        node_id = self.nodes.get(agent_name)
        if node_id is not None:
            try:
                self.itemconfig(node_id, fill=color)
            except Exception:
                pass

    def _cancel_tick(self, agent_name):
        tick = self._ticks.pop(agent_name, None)
        if tick is not None:
            try:
                tick.cancel()
            except Exception:
                pass

    def _start_working(self, agent_name):
        base_color = AGENT_COLORS[agent_name]
        bright_color = lerp_color(base_color, "#FFFFFF", 0.45)
        phase = [0]

        def on_tick():
            phase[0] = (phase[0] + 1) % 20
            amount = phase[0] / 10 if phase[0] <= 10 else (20 - phase[0]) / 10
            self._set_node_color(
                agent_name,
                lerp_color(base_color, bright_color, amount),
            )
            return True

        self._ticks[agent_name] = SafeTick(
            self,
            interval_ms=PULSE_INTERVAL_MS,
            on_tick=on_tick,
        ).start()

    def _start_done(self, agent_name):
        elapsed = [0]

        def on_tick():
            elapsed[0] += PULSE_INTERVAL_MS
            if elapsed[0] <= DONE_HOLD_MS:
                self._set_node_color(agent_name, DONE_COLOR)
                return True

            fade_amount = min(
                1.0,
                (elapsed[0] - DONE_HOLD_MS) / DONE_FADE_MS,
            )
            self._set_node_color(
                agent_name,
                lerp_color(DONE_COLOR, IDLE_COLOR, fade_amount),
            )
            if fade_amount >= 1.0:
                self._states[agent_name] = "IDLE"
                return False
            return True

        self._ticks[agent_name] = SafeTick(
            self,
            interval_ms=PULSE_INTERVAL_MS,
            on_tick=on_tick,
        ).start()

    def update_state(self, agent_name: str, state: str):
        """Apply an agent state, replacing that node's previous animation."""
        if agent_name not in AGENT_COLORS:
            return

        self._cancel_tick(agent_name)
        normalized_state = str(state).upper()
        self._states[agent_name] = normalized_state

        if normalized_state == "WORKING":
            self._set_node_color(agent_name, AGENT_COLORS[agent_name])
            self._start_working(agent_name)
        elif normalized_state == "DONE":
            self._set_node_color(agent_name, DONE_COLOR)
            self._start_done(agent_name)
        else:
            normalized_state = "IDLE"
            self._states[agent_name] = normalized_state
            self._set_node_color(agent_name, IDLE_COLOR)

    def destroy(self):
        """Cancel every animation before Tk destroys the canvas."""
        if not self._destroyed:
            for tick in list(self._ticks.values()):
                try:
                    tick.cancel()
                except Exception:
                    pass
            self._ticks.clear()
            self._destroyed = True
        super().destroy()
