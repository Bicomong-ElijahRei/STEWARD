import customtkinter as ctk
import threading
from datetime import datetime
from tkinter import messagebox, simpledialog
from core.theme import (
    BG_PANEL, CORNER_RADIUS, NEON_PURPLE, NEON_CYAN, TEXT_BRIGHT, TEXT_MUTED
)
from core.database import get_db
from core.discovery import start_discovery
from core.validator import validate_provider, ValidationResult

class SettingsTab(ctk.CTkFrame):
    AGENT_CHOICES = ("Any", "Cortex", "Foldy", "Syntax", "Scout")

    def __init__(self, parent, legacy_agent=None, main_app=None):
        # We accept legacy_agent to prevent crashes, but we don't use it anymore.
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self._pending_activations = set()
        self._assignment_dirty = False

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
        self.name_entry.bind(
            "<FocusOut>", lambda event: self._sync_assignment_to_existing_provider()
        )
        self.url_entry = self._create_input("Base URL (e.g., https://generativelanguage.googleapis.com/v1beta/openai)")
        self.url_entry.bind(
            "<KeyRelease>", lambda event: self._check_existing_credential()
        )
        self.url_entry.bind(
            "<FocusOut>", lambda event: self._check_existing_credential()
        )
        self.model_entry = self._create_input("Model Name (e.g., gemini-1.5-flash)")
        
        self.key_entry = ctk.CTkEntry(
            self.form_frame, placeholder_text="API Key", show="*", width=400
        )
        self.key_entry.pack(anchor="w", padx=20, pady=5)

        self.cred_hint_label = ctk.CTkLabel(
            self.form_frame, text="", font=("Nunito", 11), text_color=NEON_CYAN
        )
        self.cred_hint_label.pack(anchor="w", padx=20, pady=(0, 2))

        assignment_row = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        assignment_row.pack(anchor="w", padx=20, pady=5)
        ctk.CTkLabel(
            assignment_row, text="Assign to Agent", text_color=TEXT_BRIGHT
        ).pack(side="left", padx=(0, 12))
        self.assigned_agent_menu = ctk.CTkOptionMenu(
            assignment_row,
            values=list(self.AGENT_CHOICES),
            command=self._on_assignment_menu_changed,
            fg_color=NEON_PURPLE,
            button_color=NEON_PURPLE,
            button_hover_color="#9A6CE6",
        )
        self.assigned_agent_menu.set("Any")
        self.assigned_agent_menu.pack(side="left")

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
        self.verify_btn.pack(anchor="w", padx=20, pady=(10, 5))

        self.discover_btn = ctk.CTkButton(
            self.form_frame, text="Discover Free Models",
            fg_color=NEON_CYAN, hover_color="#04B5A1", text_color="#1E1E24",
            font=("Nunito", 14, "bold"),
            command=self._start_discovery,
        )
        self.discover_btn.pack(anchor="w", padx=20, pady=(0, 20))

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

    def _is_alive(self) -> bool:
        """Check if this frame and its toplevel window still exist."""
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _safe_after(self, callback):
        """Schedule a callback on the Tkinter main thread if widget still exists."""
        if not self._is_alive():
            return
        try:
            self.after(0, callback)
        except Exception:
            pass

    def _create_input(self, placeholder):
        entry = ctk.CTkEntry(self.form_frame, placeholder_text=placeholder, width=400)
        entry.pack(anchor="w", padx=20, pady=5)
        return entry

    def _on_assignment_menu_changed(self, _value):
        self._assignment_dirty = True

    def _sync_assignment_to_existing_provider(self, _event=None):
        """Reflect an existing provider's binding when its name is entered."""
        name = self.name_entry.get().strip()
        if not name:
            return
        provider = get_db().get_provider(name)
        if provider is not None:
            self.assigned_agent_menu.set(provider.get("assigned_agent") or "Any")
            self._assignment_dirty = False

    def _check_existing_credential(self):
        url = self.url_entry.get().strip()
        if not url:
            self.cred_hint_label.configure(text="")
            return
        try:
            db = get_db()
            cred = db.get_credential_by_url(url)
            if cred and cred.get("api_key"):
                self.cred_hint_label.configure(
                    text=f"ℹ️ Reusing credential saved for {cred.get('base_url_normalized')}",
                    text_color="#00FFCC",
                )
            else:
                self.cred_hint_label.configure(text="")
        except Exception:
            self.cred_hint_label.configure(text="")

    def _start_verification(self):
        name = self.name_entry.get().strip()
        url = self.url_entry.get().strip()
        model = self.model_entry.get().strip()
        key = self.key_entry.get().strip()

        if not key and url:
            try:
                db = get_db()
                cred = db.get_credential_by_url(url)
                if cred and cred.get("api_key"):
                    key = cred["api_key"]
            except Exception:
                pass

        if not all([name, url, model, key]):
            self.status_label.configure(text="❌ Please fill all fields.", text_color="red")
            return

        self.verify_btn.configure(state="disabled", text="Verifying...")
        self.status_label.configure(text="Testing API Key (Speed, Intelligence, Tools)...", text_color="orange")

        # Run validation in background thread
        threading.Thread(target=self._run_validation, args=(name, url, key, model), daemon=True).start()

    def _run_validation(self, name, url, key, model):
        try:
            result = validate_provider(name, url, key, model)
        except Exception as exc:
            result = ValidationResult(name)
            result.status = "error"
            result.error = str(exc)
            result.success = False
        
        # Update UI safely from thread
        self._safe_after(lambda: self._on_validation_complete(result, name, url, key, model))

    def _on_validation_complete(self, result, name, url, key, model):
        if not self._is_alive():
            return
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
            speed_score = result.speed_ms if result.speed_ms is not None else 9999
            intelligence_tier = result.intel_tier or "Unknown"
            supports_tools = bool(result.supports_tools)
            existing_provider = db.get_provider(name)
            assigned_agent = self.assigned_agent_menu.get()
            if existing_provider is not None and not self._assignment_dirty:
                assigned_agent = existing_provider.get("assigned_agent") or "Any"
            db.add_provider(
                name=name, 
                base_url=url, 
                api_key=key, 
                model_name=model,
                is_local=False, 
                is_active=True,
                speed_score_ms=speed_score,
                intelligence_tier=intelligence_tier,
                supports_tools=supports_tools,
                assigned_agent=assigned_agent,
            )
            db.update_provider_fields(
                name, is_active=1, cooldown_until=None, failure_count=0
            )
            self.status_label.configure(
                text=f"✅ Saved! Total request: {speed_score}ms | IQ: {intelligence_tier}",
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

    def _start_discovery(self):
        """Start catalog discovery without blocking the Tkinter event loop."""
        self.discover_btn.configure(state="disabled", text="Discovering...")
        self.status_label.configure(
            text="🔎 Discovering free OpenRouter models...", text_color=NEON_CYAN
        )
        start_discovery(callback=self._on_discovery_result)

    def _on_discovery_result(self, result):
        # start_discovery invokes this callback on its worker thread.
        self._safe_after(lambda: self._on_discovery_complete(result))

    def _on_discovery_complete(self, result):
        if not self._is_alive():
            return
        self.discover_btn.configure(state="normal", text="Discover Free Models")
        if result.error:
            self.status_label.configure(
                text=f"❌ Discovery failed: {result.error}", text_color="red"
            )
            return

        self.status_label.configure(
            text=(
                f"✅ Found {result.discovered} free models: "
                f"{result.added} added, {result.skipped} already present."
            ),
            text_color="#00FFCC",
        )
        self.refresh_provider_list()

    @staticmethod
    def _is_cooling_down(cooldown_until) -> bool:
        if not cooldown_until:
            return False
        try:
            cooldown = datetime.fromisoformat(
                str(cooldown_until).replace("Z", "+00:00")
            )
            now = datetime.now(cooldown.tzinfo) if cooldown.tzinfo else datetime.now()
            return cooldown > now
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _provider_status_dot(provider) -> str:
        if provider.get("decryption_error"):
            return "🟡"
        if provider.get("is_local", False):
            return "🟣"
        if not provider.get("is_active", False):
            return "🔴"
        if SettingsTab._is_cooling_down(provider.get("cooldown_until")):
            return "🟡"
        return "🟢"

    def refresh_provider_list(self):
        if not self._is_alive():
            return
        # Clear existing
        for widget in self.provider_list.winfo_children():
            widget.destroy()

        try:
            db = get_db()
            providers = db.get_all_providers()
            
            if not providers:
                ctk.CTkLabel(self.provider_list, text="No providers configured yet.", text_color=TEXT_MUTED).pack(pady=20)
                return

            cred_counts = {}
            for p in providers:
                cid = p.get("credential_id")
                if cid:
                    cred_counts[cid] = cred_counts.get(cid, 0) + 1

            for p in providers:
                card = ctk.CTkFrame(self.provider_list, fg_color="#2A2A35", corner_radius=10)
                card.pack(fill="x", pady=5, padx=5)
                
                # Provider state: local, disabled, cooling down, or ready.
                is_active = p.get("is_active", False)
                is_local = p.get("is_local", False)
                is_pending = p["name"] in self._pending_activations
                cooling_down = is_active and self._is_cooling_down(
                    p.get("cooldown_until")
                )
                dot = ctk.CTkLabel(
                    card, text=self._provider_status_dot(p), font=("", 16)
                )
                dot.pack(side="left", padx=10, pady=10)

                if p.get("decryption_error"):
                    status_text = " [Key unavailable: restore secret.key or re-enter API key]"
                elif is_local:
                    status_text = " [Local]" if is_active else " [Local, Disabled]"
                elif not is_active:
                    status_text = " [Disabled]"
                elif cooling_down:
                    status_text = " [Cooldown]"
                else:
                    status_text = ""
                info = ctk.CTkLabel(
                    card, 
                    text=f"{p['name']} | {p['model_name']} | total request {p['speed_score_ms']}ms | {p['intelligence_tier']}{status_text}",
                    font=("Consolas", 12),
                    text_color=TEXT_BRIGHT if is_active else TEXT_MUTED,
                    anchor="w"
                )
                info.pack(side="left", padx=10, fill="x", expand=True)

                cred_id = p.get("credential_id")
                shared_count = cred_counts.get(cred_id, 0) if cred_id else 0
                if shared_count > 1:
                    shared_badge = ctk.CTkLabel(
                        card,
                        text=f"🔗 Shared ({shared_count})",
                        font=("Nunito", 10, "bold"),
                        text_color="#00FFCC",
                        fg_color="#1E3A3A",
                        corner_radius=8,
                        padx=8,
                        pady=3,
                    )
                    shared_badge.pack(side="left", padx=4)
                elif cred_id:
                    cred_badge = ctk.CTkLabel(
                        card,
                        text="🔑 Credential",
                        font=("Nunito", 10, "bold"),
                        text_color=TEXT_MUTED,
                        fg_color="#353545",
                        corner_radius=8,
                        padx=8,
                        pady=3,
                    )
                    cred_badge.pack(side="left", padx=4)

                assignment_badge = ctk.CTkLabel(
                    card,
                    text=f"Agent: {p.get('assigned_agent') or 'Any'}",
                    font=("Nunito", 10, "bold"),
                    text_color=NEON_CYAN,
                    fg_color="#353545",
                    corner_radius=8,
                    padx=8,
                    pady=3,
                )
                assignment_badge.pack(side="left", padx=4)

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
                    state="disabled" if is_pending else "normal",
                    command=lambda name=p['name']: self._delete_provider(name)
                )
                btn_delete.pack(side="right", padx=(4, 10), pady=6)

                # Edit Key Button for credential holders
                if cred_id and not is_local:
                    btn_edit_key = ctk.CTkButton(
                        card,
                        text="Edit Key",
                        width=65,
                        height=28,
                        corner_radius=8,
                        font=("Nunito", 11, "bold"),
                        fg_color="#4F46E5",
                        hover_color="#4338CA",
                        state="disabled" if is_pending else "normal",
                        command=lambda prov=p: self._edit_shared_credential(prov),
                    )
                    btn_edit_key.pack(side="right", padx=(4, 4), pady=6)

                # Toggle Active / Disable Button
                toggle_text = (
                    "Checking..." if is_pending
                    else ("Disable" if is_active else "Enable")
                )
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
                    state="disabled" if is_pending else "normal",
                    command=lambda name=p['name'], state=is_active: self._toggle_provider(name, not state)
                )
                btn_toggle.pack(side="right", padx=(4, 4), pady=6)

        except Exception as e:
            ctk.CTkLabel(self.provider_list, text=f"Error loading DB: {e}", text_color="red").pack()

    def _edit_shared_credential(self, provider):
        dialog_parent = self.winfo_toplevel() if self._is_alive() else self
        base_url = provider.get("base_url", "")
        cred_id = provider.get("credential_id")
        try:
            db = get_db()
            all_provs = db.get_all_providers()
            sharing_providers = [
                p for p in all_provs if p.get("credential_id") == cred_id
            ]
            count = len(sharing_providers)
            new_key = simpledialog.askstring(
                "Edit Shared Credential",
                f"Enter new API key for:\n{base_url}",
                parent=dialog_parent,
                show="*",
            )
            if new_key is None:
                return
            new_key = new_key.strip()
            if not new_key:
                messagebox.showerror("Error", "API key cannot be empty.", parent=dialog_parent)
                return

            if count > 1:
                confirm = messagebox.askyesno(
                    "Confirm Shared Key Rotation",
                    f"This API key is shared by {count} providers on {base_url}.\n"
                    f"Updating it will rotate credentials for all {count} providers.\n\n"
                    "Do you want to proceed?",
                    parent=dialog_parent,
                )
                if not confirm:
                    return

            result = db.rotate_credential_by_id(
                cred_id,
                new_key,
                expected_base_url=base_url,
            )
            self.status_label.configure(
                text=(
                    f"✅ Updated credential for {result['providers_updated']} "
                    "provider(s)."
                ),
                text_color="#00FFCC",
            )
            self.refresh_provider_list()
        except Exception as exc:
            self.status_label.configure(
                text=f"❌ Error updating credential: {exc}",
                text_color="red",
            )

    @staticmethod
    def _find_reusable_key(provider, providers):
        """Find a saved key for the same endpoint, checking shared credentials first."""
        base_url = str(provider.get("base_url") or "").rstrip("/")
        if not base_url:
            return None

        try:
            db = get_db()
            cred = db.get_credential_by_url(base_url)
            if cred and cred.get("api_key"):
                return cred["api_key"], "Shared Credential Store"
        except Exception:
            pass

        for candidate in sorted(
            providers, key=lambda item: not item.get("is_active", False)
        ):
            if candidate.get("name") == provider.get("name"):
                continue
            candidate_url = str(candidate.get("base_url") or "").rstrip("/")
            key = str(candidate.get("api_key") or "").strip()
            if candidate_url == base_url and key:
                return key, candidate.get("name")
        return None

    def _toggle_provider(self, name: str, new_state: bool):
        if name in self._pending_activations:
            return

        try:
            db = get_db()
            provider = db.get_provider(name)
            if provider is None:
                raise ValueError(f"Provider '{name}' no longer exists.")

            if not new_state:
                db.update_provider_fields(name, is_active=0)
                self.status_label.configure(
                    text=f"Disabled '{name}'.", text_color=TEXT_MUTED
                )
                self.refresh_provider_list()
                return

            # Existing credentials and local providers need no extra API key.
            if provider.get("is_local") or str(provider.get("api_key") or "").strip():
                db.update_provider_fields(name, is_active=1)
                self.status_label.configure(
                    text=f"Enabled '{name}'.", text_color="#00FFCC"
                )
                self.refresh_provider_list()
                return

            reusable = self._find_reusable_key(provider, db.get_all_providers())
            if reusable:
                key, key_source = reusable
            else:
                dialog_parent = self.winfo_toplevel() if self._is_alive() else self
                key = simpledialog.askstring(
                    "API Key Required",
                    f"Enter an API key for '{name}'\n({provider['base_url']}):",
                    parent=dialog_parent,
                    show="*",
                )
                if key is None:
                    self.status_label.configure(
                        text=f"Activation of '{name}' cancelled.",
                        text_color=TEXT_MUTED,
                    )
                    return
                key = key.strip()
                if not key:
                    self.status_label.configure(
                        text="❌ An API key is required to enable this provider.",
                        text_color="red",
                    )
                    return
                key_source = None

            self._pending_activations.add(name)
            source_text = f" using the saved key from '{key_source}'" if key_source else ""
            self.status_label.configure(
                text=f"🔐 Validating '{name}'{source_text}...", text_color="orange"
            )
            self.refresh_provider_list()
            threading.Thread(
                target=self._run_provider_activation,
                args=(provider, key, key_source),
                daemon=True,
            ).start()
        except Exception as e:
            self._pending_activations.discard(name)
            self.status_label.configure(
                text=f"❌ Error updating provider: {e}", text_color="red"
            )

    def _run_provider_activation(self, provider, key, key_source):
        name = provider["name"]
        try:
            result = validate_provider(
                name, provider["base_url"], key, provider.get("model_name") or "default"
            )
        except Exception as exc:
            error = str(exc)
            self._safe_after(
                lambda error=error: self._on_activation_failed(name, error)
            )
            return

        self._safe_after(
            lambda: self._on_provider_activation_complete(
                provider, key, key_source, result
            )
        )

    def _on_activation_failed(self, name, error):
        if not self._is_alive():
            return
        self._pending_activations.discard(name)
        self.status_label.configure(
            text=f"❌ Could not activate '{name}': {error}", text_color="red"
        )
        self.refresh_provider_list()

    def _on_provider_activation_complete(self, provider, key, key_source, result):
        if not self._is_alive():
            return
        name = provider["name"]
        self._pending_activations.discard(name)
        if not result.success:
            self.status_label.configure(
                text=(
                    f"❌ Could not activate '{name}': "
                    f"{result.error or 'validation failed'}"
                ),
                text_color="red",
            )
            self.refresh_provider_list()
            return

        try:
            db = get_db()
            speed_score = result.speed_ms if result.speed_ms is not None else 9999
            intelligence_tier = result.intel_tier or "Unknown"
            supports_tools = bool(result.supports_tools)
            db.add_provider(
                name=name,
                base_url=provider["base_url"],
                api_key=key,
                model_name=provider.get("model_name") or "default",
                is_local=provider.get("is_local", False),
                is_active=True,
                speed_score_ms=speed_score,
                intelligence_tier=intelligence_tier,
                supports_tools=supports_tools,
                assigned_agent=provider.get("assigned_agent") or "Any",
            )
            db.update_provider_fields(
                name, is_active=1, cooldown_until=None, failure_count=0
            )
            source_text = f" using the saved key from '{key_source}'" if key_source else ""
            self.status_label.configure(
                text=f"✅ Activated '{name}'{source_text}.", text_color="#00FFCC"
            )
        except Exception as e:
            self.status_label.configure(
                text=f"❌ DB Error activating '{name}': {e}", text_color="red"
            )
        self.refresh_provider_list()

    def _delete_provider(self, name: str):
        dialog_parent = self.winfo_toplevel() if self._is_alive() else self
        confirmed = messagebox.askyesno(
            "Delete Provider",
            f"Are you sure you want to delete '{name}' from the API Hub?\nThis cannot be undone.",
            parent=dialog_parent
        )
        if confirmed:
            try:
                db = get_db()
                db.delete_provider(name)
                self.refresh_provider_list()
                self.status_label.configure(text=f"Removed provider '{name}'.", text_color=TEXT_MUTED)
            except Exception as e:
                self.status_label.configure(text=f"❌ Error deleting provider: {e}", text_color="red")