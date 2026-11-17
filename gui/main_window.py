import tkinter as tk
from tkinter import ttk, messagebox
import pystray
from PIL import Image, ImageDraw
import threading
import logging

from agent.core import StewardAgent
from agents.supervisor import SupervisorAgent
from agents.file_agent import FileAgent
from core.litellm_client import LiteLLMClient
from gui.chat_tab import ChatTab
from gui.organizer_tab import OrganizerTab
from gui.settings_tab import SettingsTab

logger = logging.getLogger(__name__)


class StewardGUI:
    def __init__(self, root):
        self.root = root
        root.title("STEWARD – AI File Manager")
        root.geometry("800x600")
        root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Initialize core LLM client
        self.llm_client = LiteLLMClient()

        # Initialize agents
        self.supervisor = SupervisorAgent(llm_client=self.llm_client)
        self.file_agent = FileAgent(llm_client=self.llm_client, dry_run=True)
        self.legacy_agent = StewardAgent()  # Backward compatibility

        self.observer = None
        self.daemon_running = False

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Create tabs - pass both supervisor and file_agent
        self.chat_tab = ChatTab(self.notebook, self.supervisor, self.file_agent)
        self.org_tab = OrganizerTab(self.notebook, self.file_agent, self)
        self.settings_tab = SettingsTab(self.notebook, self.legacy_agent, self)

        self.notebook.add(self.chat_tab.frame, text="Chat")
        self.notebook.add(self.org_tab.frame, text="File Organizer")
        self.notebook.add(self.settings_tab.frame, text="Settings")

        self.setup_tray()

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