#!/usr/bin/env python3
"""
STEWARD - Smart Task Execution and Workflow Automation for Resource Directing
Entry point.
"""

import customtkinter as ctk
from gui.main_window import StewardGUI

if __name__ == "__main__":
    # Set the default appearance mode and color theme
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    
    root = ctk.CTk()
    app = StewardGUI(root)
    root.mainloop()