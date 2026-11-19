import customtkinter as ctk
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw
import threading
import logging

from agent.core import StewardAgent
from agents.supervisor import SupervisorAgent
from agents.file_agent import FileAgent
from core.litellm_client import LiteLLMClient
from core.theme import (
    apply_theme, BG_DEEP_SPACE, BG_PANEL, CORNER_RADIUS, NEON_PURPLE
)
from gui.chat_tab import ChatTab
from gui.organizer_tab import OrganizerTab
from gui.settings_tab import SettingsTab
from gui.live_feed import LiveFeedWidget

logger = logging.getLogger(__name__)


class StewardGUI:
    def __init__(self, root):
        self.root = root
        root.title("STEWARD – Cyber-Kawaii Mission Control")
        root.geometry("1200x800")
        root.configure(fg_color=BG_DEEP_SPACE)
        root.protocol("WM_DELETE_WINDOW", self.on_closing)

        apply_theme()

        self.llm_client = LiteLLMClient()
        self.supervisor = SupervisorAgent(llm_client=self.llm_client)
        self.file_agent = FileAgent(llm_client=self.llm_client, dry_run=True)
        self.legacy_agent = StewardAgent()

        self.observer = None
        self.daemon_running = False

        self.main_container = ctk.CTkFrame(root, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=12, pady=12)

        self.left_panel = ctk.CTkFrame(
            self.main_container, fg_color=BG_PANEL, corner_radius=CORNER_RADIUS
        )
        self.left_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.right_panel = ctk.CTkFrame(
            self.main_container, fg_color=BG_PANEL, corner_radius=CORNER_RADIUS, width=400
        )
        self.right_panel.pack(side="right", fill="both", expand=False, padx=(6, 0))
        self.right_panel.pack_propagate(False)

        self.feed_header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.feed_header.pack(fill="x", padx=16, pady=(16, 8))

        self.feed_title = ctk.CTkLabel(
            self.feed_header,
            text="📡 LIVE FEED",
            font=("Nunito", 16, "bold"),
            text_color=NEON_PURPLE,
        )
        self.feed_title.pack(side="left")

        self.feed_clear = ctk.CTkButton(
            self.feed_header,
            text="Clear",
            width=60,
            height=28,
            fg_color="#3A3A4A",
            hover_color="#4A4A5A",
            font=("Nunito", 10),
            command=self.live_feed_clear,
        )
        self.feed_clear.pack(side="right")

        self.live_feed = LiveFeedWidget(self.right_panel, width=360)
        self.live_feed.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.live_feed.agent_idle("Cortex")
        self.live_feed.agent_idle("Foldy")

        self.chat_tab = ChatTab(self.left_panel, self.supervisor, self.file_agent, self.live_feed)
        self.chat_tab.pack(fill="both", expand=True, padx=12, pady=12)

        self.setup_tray()

    def live_feed_clear(self):
        self.live_feed.clear()

    def feed_agent_working(self, agent_name: str, detail: str = ""):
        self.live_feed.agent_working(agent_name, detail)

    def feed_agent_done(self, agent_name: str, detail: str = ""):
        self.live_feed.agent_done(agent_name, detail)

    def feed_agent_idle(self, agent_name: str):
        self.live_feed.agent_idle(agent_name)

    def setup_tray(self):
        image = Image.new('RGB', (64, 64), color='black')
        draw = ImageDraw.Draw(image)
        draw.rectangle([10, 10, 54, 54], fill='white')
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.root.deiconify()),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("steward", image, "STEWARD", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

    def hide_window(self):
        self.root.withdraw()
        self.tray_icon.notify("STEWARD is still running in the background", "STEWARD")

    def quit_app(self):
        self.tray_icon.stop()
        self.root.quit()

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit STEWARD?"):
            self.root.destroy()