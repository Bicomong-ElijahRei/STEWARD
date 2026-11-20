import customtkinter as ctk
import threading
from tkinter import messagebox
from core.theme import (
    BG_PANEL, CORNER_RADIUS, NEON_PURPLE, NEON_CYAN, TEXT_BRIGHT, TEXT_MUTED
)
from core.database import get_db
from core.validator import validate_provider

class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent, legacy_agent=None, main_app=None):
        # We accept legacy_agent to prevent crashes, but we don't use it anymore.
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app

        # Title
        self.title = ctk.CTkLabel(
            self, text="🔌 API Hub", 
            font=("Nunito", 24, "bold"), text_color=NEON_PURPLE
        )
        self.title.pack(anchor="w", pady=(0, 20))

        # --- Add Provider Form ---
        self.form_frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=CORNER_RADIUS)
        self.form_frame.pack(fill="x", padx=10, pady=10)

        self.form_title = ctk.CTkLabel(
            self.form_frame, text="Add New Brain", 
            font=("Nunito", 16, "bold"), text_color=TEXT_BRIGHT
        )
        self.form_title.pack(anchor="w", padx=20, pady=(15, 10))

        # Inputs
        self.name_entry = self._create_input("Provider Name (e.g., Gemini)")
        self.url_entry = self._create_input("Base URL (e.g., https://generativelanguage.googleapis.com/v1beta/openai)")
        self.model_entry = self._create_input("Model Name (e.g., gemini-1.5-flash)")
        
        self.key_entry = ctk.CTkEntry(
            self.form_frame, placeholder_text="API Key", show="*", width=400
        )
        self.key_entry.pack(anchor="w", padx=20, pady=5)

        self.status_label = ctk.CTkLabel(
            self.form_frame, text="", font=("Nunito", 12), text_color=TEXT_MUTED
        )
        self.status_label.pack(anchor="w", padx=20, pady=(5, 0))

        self.verify_btn = ctk.CTkButton(
            self.form_frame, text="Verify & Save", 
            fg_color=NEON_PURPLE, hover_color="#9A6CE6",
            font=("Nunito", 14, "bold"),
            command=self._start_verification
        )
        self.verify_btn.pack(anchor="w", padx=20, pady=(10, 20))

        # --- List of Active Providers ---
        self.list_title = ctk.CTkLabel(
            self, text="Active Providers", 
            font=("Nunito", 18, "bold"), text_color=TEXT_BRIGHT
        )
        self.list_title.pack(anchor="w", pady=(20, 10))

        self.provider_list = ctk.CTkScrollableFrame(
            self, fg_color=BG_PANEL, corner_radius=CORNER_RADIUS
        )
        self.provider_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.refresh_provider_list()

    def _create_input(self, placeholder):
        entry = ctk.CTkEntry(self.form_frame, placeholder_text=placeholder, width=400)
        entry.pack(anchor="w", padx=20, pady=5)
        return entry

    def _start_verification(self):
        name = self.name_entry.get().strip()
        url = self.url_entry.get().strip()
        model = self.model_entry.get().strip()
        key = self.key_entry.get().strip()

        if not all([name, url, model, key]):
            self.status_label.configure(text="❌ Please fill all fields.", text_color="red")
            return

        self.verify_btn.configure(state="disabled", text="Verifying...")
        self.status_label.configure(text="Testing API Key (Speed, Intelligence, Tools)...", text_color="orange")

        # Run validation in background thread
        threading.Thread(target=self._run_validation, args=(name, url, key, model), daemon=True).start()

    def _run_validation(self, name, url, key, model):
        result = validate_provider(name, url, key, model)
        
        # Update UI safely from thread
        self.after(0, lambda: self._on_validation_complete(result, name, url, key, model))

    def _on_validation_complete(self, result, name, url, key, model):
        self.verify_btn.configure(state="normal", text="Verify & Save")
        
        if result.status == "invalid_key":
            self.status_label.configure(text=f"❌ {result.error}", text_color="red")
            return
        
        if result.status == "rate_limited":
            self.status_label.configure(text="⚠️ Rate Limited. Saving anyway...", text_color="orange")
        elif not result.success:
            self.status_label.configure(text=f"❌ Failed: {result.error}", text_color="red")
            return
        else:
            self.status_label.configure(text="✅ Key Validated!", text_color="#00FFCC")

        # Save to SQLite Database
        try:
            db = get_db()
            # Assuming add_provider accepts these kwargs based on the schema
            db.add_provider(
                name=name, 
                base_url=url, 
                api_key=key, 
                model_name=model,
                is_local=False, 
                is_active=True,
                speed_score_ms=result.speed_ms,
                intelligence_tier=result.intel_tier,
                supports_tools=result.supports_tools
            )
            self.status_label.configure(
                text=f"✅ Saved! Speed: {result.speed_ms}ms | IQ: {result.intel_tier}", 
                text_color="#00FFCC"
            )
            self.refresh_provider_list()
            
            # Clear inputs
            self.name_entry.delete(0, 'end')
            self.url_entry.delete(0, 'end')
            self.model_entry.delete(0, 'end')
            self.key_entry.delete(0, 'end')

        except Exception as e:
            self.status_label.configure(text=f"❌ DB Error: {str(e)}", text_color="red")

    def refresh_provider_list(self):
        # Clear existing
        for widget in self.provider_list.winfo_children():
            widget.destroy()

        try:
            db = get_db()
            providers = db.get_all_providers()
            
            if not providers:
                ctk.CTkLabel(self.provider_list, text="No providers configured yet.", text_color=TEXT_MUTED).pack(pady=20)
                return

            for p in providers:
                card = ctk.CTkFrame(self.provider_list, fg_color="#2A2A35", corner_radius=10)
                card.pack(fill="x", pady=5, padx=5)
                
                # Active status dot
                is_active = p.get('is_active', False)
                dot = ctk.CTkLabel(card, text="🟢" if is_active else "⚪", font=("", 16))
                dot.pack(side="left", padx=10, pady=10)
                
                status_text = "" if is_active else " [Disabled]"
                info = ctk.CTkLabel(
                    card, 
                    text=f"{p['name']} | {p['model_name']} | {p['speed_score_ms']}ms | {p['intelligence_tier']}{status_text}", 
                    font=("Consolas", 12),
                    text_color=TEXT_BRIGHT if is_active else TEXT_MUTED,
                    anchor="w"
                )
                info.pack(side="left", padx=10, fill="x", expand=True)

                # Delete Button
                btn_delete = ctk.CTkButton(
                    card,
                    text="Delete",
                    width=65,
                    height=28,
                    corner_radius=8,
                    font=("Nunito", 11, "bold"),
                    fg_color="#DC2626",
                    hover_color="#B91C1C",
                    command=lambda name=p['name']: self._delete_provider(name)
                )
                btn_delete.pack(side="right", padx=(4, 10), pady=6)

                # Toggle Active / Disable Button
                toggle_text = "Disable" if is_active else "Enable"
                toggle_fg = "#4A4A5A" if is_active else "#10B981"
                toggle_hover = "#5A5A6A" if is_active else "#059669"
                btn_toggle = ctk.CTkButton(
                    card,
                    text=toggle_text,
                    width=75,
                    height=28,
                    corner_radius=8,
                    font=("Nunito", 11, "bold"),
                    fg_color=toggle_fg,
                    hover_color=toggle_hover,
                    command=lambda name=p['name'], state=is_active: self._toggle_provider(name, not state)
                )
                btn_toggle.pack(side="right", padx=(4, 4), pady=6)

        except Exception as e:
            ctk.CTkLabel(self.provider_list, text=f"Error loading DB: {e}", text_color="red").pack()

    def _toggle_provider(self, name: str, new_state: bool):
        try:
            db = get_db()
            db.update_provider_fields(name, is_active=1 if new_state else 0)
            self.refresh_provider_list()
        except Exception as e:
            self.status_label.configure(text=f"❌ Error updating provider: {e}", text_color="red")

    def _delete_provider(self, name: str):
        confirmed = messagebox.askyesno(
            "Delete Provider",
            f"Are you sure you want to delete '{name}' from the API Hub?\nThis cannot be undone."
        )
        if confirmed:
            try:
                db = get_db()
                db.delete_provider(name)
                self.refresh_provider_list()
                self.status_label.configure(text=f"Removed provider '{name}'.", text_color=TEXT_MUTED)
            except Exception as e:
                self.status_label.configure(text=f"❌ Error deleting provider: {e}", text_color="red")