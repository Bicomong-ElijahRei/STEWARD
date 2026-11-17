#!/usr/bin/env python3
"""
STEWARD - Smart Task Execution and Workflow Automation for Resource Directing
Entry point.
"""

import tkinter as tk
from gui.main_window import StewardGUI

if __name__ == "__main__":
    root = tk.Tk()
    app = StewardGUI(root)
    root.mainloop()