import customtkinter as ctk
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw
import threading
import logging

from agents.supervisor import SupervisorAgent
from agents.file_agent import FileAgent
from agents.coding_agent import CodingAgent
from agents.plan_agent import PlanAgent
from core.router import APIManager
from core.theme import (
    apply_theme, BG_DEEP_SPACE, BG_PANEL, CORNER_RADIUS, NEON_PURPLE,
    NEON_CYAN, TEXT_BRIGHT, TEXT_MUTED, BORDER_COLOR,
)
from gui.anim import SafeTick, lerp_color
from gui.chat_tab import ChatTab
from gui.organizer_tab import OrganizerTab
from gui.settings_tab import SettingsTab
from gui.live_feed import LiveFeedWidget

logger = logging.getLogger(__name__)


class StewardGUI:
    def __init__(self, root):
        self.root = root
        root.title("STEWARD – Cyber-Kawaii Mission Control")
        root.geometry("1400x850")
        root.configure(fg_color=BG_DEEP_SPACE)
        root.protocol("WM_DELETE_WINDOW", self.hide_window)

        apply_theme()

        from core.database import init_db
        init_db() # Initialize SQLite Database

        self.api_manager = APIManager()
        self.supervisor = SupervisorAgent(api_manager=self.api_manager)
        self.file_agent = FileAgent(api_manager=self.api_manager, dry_run=True)
        self.coding_agent = CodingAgent(api_manager=self.api_manager)
        self.plan_agent = PlanAgent(api_manager=self.api_manager)

        self.observer = None
        self.daemon_running = False

        self.current_tab = None
        self.tabs = {}
        self._fade_tick = None

        self.outer = ctk.CTkFrame(root, fg_color=BG_DEEP_SPACE)
        self.outer.pack(fill="both", expand=True, padx=0, pady=0)

        self.sidebar = ctk.CTkFrame(self.outer, fg_color="#25252E", corner_radius=0, width=200)
        self.sidebar.pack(side="left", fill="y", padx=0, pady=0)
        self.sidebar.pack_propagate(False)

        self.sidebar_title = ctk.CTkLabel(
            self.sidebar, text="STEWARD",
            font=("Nunito", 20, "bold"), text_color=NEON_PURPLE,
        )
        self.sidebar_title.pack(pady=(30, 10))

        self.sidebar_subtitle = ctk.CTkLabel(
            self.sidebar, text="Mission Control",
            font=("Nunito", 11), text_color=TEXT_MUTED,
        )
        self.sidebar_subtitle.pack(pady=(0, 30))

        self.provider_status_label = ctk.CTkLabel(
            self.sidebar,
            text="Provider: not used yet",
            font=("Consolas", 9),
            text_color=TEXT_MUTED,
            wraplength=170,
            justify="center",
        )
        self.provider_status_label.pack(pady=(0, 20), padx=12)

        self.nav_buttons = {}
        nav_items = [
            ("chat", "💬 Chat", NEON_PURPLE),
            ("organizer", "📁 Organizer", NEON_CYAN),
            ("settings", "🔌 API Hub", "#D97706"),
        ]

        for tab_id, label, color in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=label, width=160, height=40, corner_radius=10,
                font=("Nunito", 13, "bold"), fg_color="transparent",
                hover_color="#3A3A4A", text_color=TEXT_BRIGHT,
                border_width=2, border_color=color,
                command=lambda t=tab_id: self.switch_tab(t),
            )
            btn.pack(pady=6, padx=20)
            self.nav_buttons[tab_id] = btn

        self.content = ctk.CTkFrame(self.outer, fg_color=BG_DEEP_SPACE, corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True, padx=0, pady=0)

        self.tabs["chat"] = ChatTab(
            self.content,
            self.supervisor,
            self.file_agent,
            None,
            provider_callback=self.show_provider_used,
            coding_agent=self.coding_agent,
            plan_agent=self.plan_agent,
        )
        self.tabs["organizer"] = OrganizerTab(self.content, self.file_agent, self)
        self.tabs["settings"] = SettingsTab(self.content, main_app=self)

        self.switch_tab("chat")

        self.setup_tray()

    def _fade_in_content(self):
        """Animate the content frame fading in from black."""
        if self._fade_tick:
            self._fade_tick.cancel()
            self._fade_tick = None
        duration_ms = 200
        steps = 10
        interval = duration_ms // steps
        step = [0]

        def on_tick():
            step[0] += 1
            t = step[0] / steps
            # Interpolate from black (#000000) to BG_DEEP_SPACE
            current_color = lerp_color("#000000", BG_DEEP_SPACE, t)
            self.content.configure(fg_color=current_color)
            return t < 1.0

        self._fade_tick = SafeTick(self.content, interval, on_tick).start()

    def switch_tab(self, tab_name):
        """Hide the current tab and show the requested one."""
        if self.current_tab is not None:
            self.tabs[self.current_tab].pack_forget()

        self.tabs[tab_name].pack(fill="both", expand=True, padx=20, pady=20)
        self._fade_in_content()
        if tab_name == "settings":
            # Repopulate canvas-hosted cards after pack_forget()/pack() and
            # show the latest provider state whenever API Hub is opened.
            self.tabs[tab_name].refresh_provider_list()
        self.current_tab = tab_name

        for tid, btn in self.nav_buttons.items():
            if tid == tab_name:
                color_map = {"chat": NEON_PURPLE, "organizer": NEON_CYAN, "settings": "#D97706"}
                btn.configure(fg_color=color_map.get(tid, NEON_PURPLE), text_color="#FFFFFF")
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_BRIGHT)

    def show_provider_used(self, agent_name, provider_info):
        """Display the provider and model selected by the router."""
        if not provider_info:
            return
        provider = provider_info.get("provider", "Unknown")
        model = provider_info.get("model", "default")
        text = f"{agent_name}\n{provider}\n{model}"
        self.root.after(
            0, lambda: self.provider_status_label.configure(text=text)
        )

    def live_feed_clear(self):
        chat_tab = self.tabs.get("chat")
        if chat_tab and chat_tab.live_feed:
            chat_tab.live_feed.clear()

    def feed_agent_working(self, agent_name: str, detail: str = ""):
        chat_tab = self.tabs.get("chat")
        if chat_tab and chat_tab.live_feed:
            chat_tab.live_feed.agent_working(agent_name, detail)

    def feed_agent_done(self, agent_name: str, detail: str = ""):
        chat_tab = self.tabs.get("chat")
        if chat_tab and chat_tab.live_feed:
            chat_tab.live_feed.agent_done(agent_name, detail)

    def feed_agent_idle(self, agent_name: str):
        chat_tab = self.tabs.get("chat")
        if chat_tab and chat_tab.live_feed:
            chat_tab.live_feed.agent_idle(agent_name)

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
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.notify("STEWARD is running in the background", "STEWARD")

    def _perform_shutdown(self):
        """Centralized shutdown: stop observer, tray, then quit."""
        organizer = self.tabs.get("organizer")
        if organizer is not None:
            stop_scheduled_scan = getattr(organizer, "stop_scheduled_scan", None)
            if callable(stop_scheduled_scan):
                stop_scheduled_scan()
            if getattr(organizer, "daemon_running", False):
                organizer.stop_daemon()
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.stop()
        if getattr(self, "_fade_tick", None):
            self._fade_tick.cancel()
            self._fade_tick = None
        self.root.quit()
        self.root.destroy()

    def quit_app(self):
        # Marshaled to main thread if called from tray
        self.root.after(0, self._perform_shutdown)
