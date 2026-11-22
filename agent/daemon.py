import os
import time
import re
import shutil
import threading
from collections import OrderedDict
from threading import Event
from watchdog.events import FileSystemEventHandler
from utils.helpers import read_file_content_simple

# tkinter import removed - not used in daemon module

class FileCreationHandler(FileSystemEventHandler):
    def __init__(self, agent, dest_base, root):
        self.agent = agent
        self.dest_base = dest_base
        self.root = root
        self.last_processed = OrderedDict()

    def on_created(self, event):
        if event.is_directory:
            return
        filepath = event.src_path
        if filepath in self.last_processed:
            self.last_processed.move_to_end(filepath)
            return
        self.last_processed[filepath] = True
        while len(self.last_processed) > 1000:
            self.last_processed.popitem(last=False)
        threading.Thread(target=self._process_file, args=(filepath,), daemon=True).start()

    @staticmethod
    def _wait_until_stable(filepath, timeout=10.0, interval=0.5):
        deadline = time.time() + timeout
        last_size = -1
        while time.time() < deadline:
            try:
                size = os.path.getsize(filepath)
            except OSError:
                return False
            if size == last_size:
                return True
            last_size = size
            time.sleep(interval)
        return False

    def _process_file(self, filepath):
        try:
            if not self._wait_until_stable(filepath):
                print(f"[Daemon] Skipped (still growing or missing): {filepath}")
                return
            result = self.agent.categorise_file(
                filepath, self.dest_base, self.root, dry_run=False
            )
            print(f"[Daemon] {result}")
        except Exception as e:
            print(f"[Daemon] Error: {e}")

# This function will be added to StewardAgent as a method, but we define it here for clarity.
# Actually it's part of the agent, so we'll keep it in the agent class.
# For modularity, we'll inject the method into StewardAgent later, but for now I'll put it inside core.py.