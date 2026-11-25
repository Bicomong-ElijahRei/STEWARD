"""
STEWARD Cyber-Kawaii Mission Control Theme

Deep space-gray background with vibrant neon accents.
Rounded corners throughout. Rounded font for chat, monospaced for logs.
"""

import customtkinter as ctk

# ── Color Palette ──────────────────────────────────────────────────────────
BG_DEEP_SPACE = "#1E1E24"        # Main background
BG_PANEL = "#2A2A35"             # Secondary panels / frames
BG_INPUT = "#353545"             # Input fields
BG_HOVER = "#3E3E50"             # Hover states

NEON_PURPLE = "#BB86FC"          # Cortex (Supervisor) accent
NEON_CYAN = "#03DAC6"            # Foldy (File) accent
NEON_LIME = "#CCFF00"            # approval accent
NEON_BLUE = "#3700FF"            # Scout (Browser) accent
NEON_ORANGE = "#FF9800"          # Syntax (Coding) accent

TEXT_BRIGHT = "#FFFFFF"
TEXT_MUTED = "#B0B0C0"
TEXT_DIM = "#6E6E80"
BORDER_COLOR = "#4A4A5A"

# ── Typography ─────────────────────────────────────────────────────────────
FONT_ROUNDED = ("Nunito", 12)            # Chat, labels, friendly UI
FONT_ROUNDED_BOLD = ("Nunito", 12, "bold")
FONT_ROUNDED_LG = ("Nunito", 14, "bold")
FONT_MONO = ("Consolas", 11)             # Logs, data, code
FONT_MONO_BOLD = ("Consolas", 11, "bold")
FONT_MONO_SM = ("Consolas", 9)

# ── Widget Styling ─────────────────────────────────────────────────────────
CORNER_RADIUS = 16
BUTTON_HEIGHT = 40
INPUT_HEIGHT = 36


def apply_theme():
    """Apply the global Cyber-Kawaii theme to customtkinter."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


# ── Agent Color Mapping ────────────────────────────────────────────────────
AGENT_COLORS = {
    "Cortex": NEON_PURPLE,
    "Foldy": NEON_CYAN,
    "Scout": NEON_BLUE,
    "Syntax": NEON_ORANGE,
}