import os
import time
import re
import shutil
import threading
from threading import Event
from watchdog.events import FileSystemEventHandler
from utils.helpers import read_file_content_simple

# tkinter import removed - not used in daemon module

class FileCreationHandler(FileSystemEventHandler):
    def __init__(self, agent, dest_base, root):
        self.agent = agent
        self.dest_base = dest_base
        self.root = root
        self.last_processed = set()

    def on_created(self, event):
        if event.is_directory:
            return
        time.sleep(0.5)
        filepath = event.src_path
        if filepath in self.last_processed:
            return
        self.last_processed.add(filepath)
        if len(self.last_processed) > 1000:
            self.last_processed.clear()
        threading.Thread(target=self._process_file, args=(filepath,), daemon=True).start()

    def _process_file(self, filepath):
        try:
            result = self.agent.categorise_file(filepath, self.dest_base, self.root)
            print(f"[Daemon] {result}")
        except Exception as e:
            print(f"[Daemon] Error: {e}")

# This function will be added to StewardAgent as a method, but we define it here for clarity.
# Actually it's part of the agent, so we'll keep it in the agent class.
# For modularity, we'll inject the method into StewardAgent later, but for now I'll put it inside core.py.