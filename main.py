import os
import json
import datetime
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin
import subprocess

import customtkinter as ctk
import tkinter as tk
from tkinter import Menu, messagebox

import requests

from login import coceso_login, get_concerns, set_active_concern
import Patadmin_communication as PatAdmin
import print as print_util
import ecard
from Patient import Patient


@dataclass
class AppState:
	server_url: str = ""
	username: str = ""
	remember: bool = False
	jsessionid: str | None = None
	cookies: dict[str, str] | None = None
	active_concern_name: str | None = None


@dataclass
class AppSettings:
	printing_enabled: bool = True
	auto_refresh_enabled: bool = True
	ecard_enabled: bool = True
	refresh_interval_sec: int = 10
	printer_name: str = "Generic / Text Only"
	fullscreen: bool = False
	theme: str = "blue"
	appearance_mode: str = "System"
	language: str = "en"


class Translator:
	def __init__(self, locale_dir: str, language: str = "en"):
		self.locale_dir = locale_dir
		self.language = language
		self.translations: dict[str, str] = {}
		self.load_language(language)

	def load_language(self, language: str) -> None:
		self.language = language
		
		# 1. Load fallback (English)
		fallback_path = os.path.join(self.locale_dir, "en.json")
		fallback_data = {}
		if os.path.exists(fallback_path):
			try:
				with open(fallback_path, "r", encoding="utf-8") as f:
					fallback_data = json.load(f)
			except Exception:
				pass

		# 2. Load target language
		target_path = os.path.join(self.locale_dir, f"{language}.json")
		target_data = {}
		if language != "en" and os.path.exists(target_path):
			try:
				with open(target_path, "r", encoding="utf-8") as f:
					target_data = json.load(f)
			except Exception:
				pass
		elif language == "en":
			target_data = fallback_data

		# 3. Merge
		self.translations = fallback_data.copy()
		self.translations.update(target_data)

	def get_available_languages(self) -> list[tuple[str, str]]:
		results = []
		if not os.path.exists(self.locale_dir):
			return [("en", "English")]

		for filename in os.listdir(self.locale_dir):
			if filename.endswith(".json"):
				code = filename[:-5]
				name = code
				try:
					with open(os.path.join(self.locale_dir, filename), "r", encoding="utf-8") as f:
						data = json.load(f)
						name = data.get("_language_name", code)
				except Exception:
					pass
				results.append((code, name))
		
		# Sort: English first, then others alphabetically by code
		results.sort(key=lambda x: (0 if x[0] == "en" else 1, x[0]))
		return results

	def get(self, key: str, *args) -> str:
		val = self.translations.get(key, key)
		if args:
			try:
				return val.format(*args)
			except Exception:
				return val
		return val


_translator = Translator(os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales"))


def tr(key: str, *args) -> str:
	return _translator.get(key, *args)


def _credentials_path() -> str:
	here = os.path.dirname(os.path.abspath(__file__))
	return os.path.join(here, "login_credentials.txt")


def _settings_path() -> str:
	here = os.path.dirname(os.path.abspath(__file__))
	return os.path.join(here, "app_settings.json")


def load_settings() -> AppSettings:
	path = _settings_path()
	if not os.path.exists(path):
		return AppSettings()
	try:
		with open(path, "r", encoding="utf-8") as f:
			data = json.load(f)
	except Exception:
		return AppSettings()

	settings = AppSettings()
	if isinstance(data, dict):
		settings.printing_enabled = bool(data.get("printing_enabled", settings.printing_enabled))
		settings.auto_refresh_enabled = bool(data.get("auto_refresh_enabled", settings.auto_refresh_enabled))
		settings.ecard_enabled = bool(data.get("ecard_enabled", settings.ecard_enabled))
		try:
			settings.refresh_interval_sec = int(data.get("refresh_interval_sec", settings.refresh_interval_sec))
		except Exception:
			pass
		printer_name = data.get("printer_name")
		if isinstance(printer_name, str) and printer_name.strip():
			settings.printer_name = printer_name.strip()
		
		settings.fullscreen = bool(data.get("fullscreen", settings.fullscreen))
		
		theme = data.get("theme")
		if isinstance(theme, str) and theme.strip():
			settings.theme = theme.strip()
			
		appearance_mode = data.get("appearance_mode")
		if isinstance(appearance_mode, str) and appearance_mode.strip():
			settings.appearance_mode = appearance_mode.strip()

		language = data.get("language")
		if isinstance(language, str) and language.strip():
			settings.language = language.strip()

	# Clamp to sane minimum
	if settings.refresh_interval_sec < 2:
		settings.refresh_interval_sec = 2
	return settings


def save_settings(settings: AppSettings) -> None:
	path = _settings_path()
	data = {
		"printing_enabled": bool(settings.printing_enabled),
		"auto_refresh_enabled": bool(settings.auto_refresh_enabled),
		"ecard_enabled": bool(settings.ecard_enabled),
		"refresh_interval_sec": int(settings.refresh_interval_sec),
		"printer_name": str(settings.printer_name or "").strip(),
		"fullscreen": bool(settings.fullscreen),
		"theme": str(settings.theme),
		"appearance_mode": str(settings.appearance_mode),
		"language": str(settings.language),
	}
	with open(path, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent=2)


def load_saved_credentials() -> AppState:
	path = _credentials_path()
	if not os.path.exists(path):
		return AppState()

	try:
		with open(path, "r", encoding="utf-8") as f:
			lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
	except OSError:
		return AppState()

	server = lines[0] if len(lines) >= 1 else ""
	user = lines[1] if len(lines) >= 2 else ""

	# If a username is present, assume user intended it as a saved login.
	remember = bool(user)
	return AppState(server_url=server, username=user, remember=remember)


def save_credentials(server_url: str, username: str) -> None:
	path = _credentials_path()
	with open(path, "w", encoding="utf-8") as f:
		f.write((server_url or "").strip() + "\n")
		f.write((username or "").strip() + "\n")


def save_server_only(server_url: str) -> None:
	# Preserve existing username if present
	existing = load_saved_credentials()
	save_credentials(server_url, existing.username)


class ServerDialog(ctk.CTkToplevel):
	def __init__(self, master: ctk.CTk, initial_url: str):
		super().__init__(master)

		self.title(tr("server"))
		self.resizable(False, False)

		self._value: str | None = None
		self.protocol("WM_DELETE_WINDOW", self._on_cancel)

		self.grid_columnconfigure(0, weight=1)

		ctk.CTkLabel(self, text=tr("server_url")).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
		self.entry = ctk.CTkEntry(self, width=420)
		self.entry.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
		self.entry.insert(0, initial_url or "")

		btns = ctk.CTkFrame(self, fg_color="transparent")
		btns.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="e")

		ctk.CTkButton(btns, text=tr("cancel"), command=self._on_cancel).pack(side="right")
		ctk.CTkButton(btns, text=tr("ok"), command=self._on_ok).pack(side="right", padx=(0, 8))

		# Hotkeys
		self.bind("<Return>", lambda _e: self._on_ok())
		self.bind("<Escape>", lambda _e: self._on_cancel())

		self.after(50, self.entry.focus_set)
		self.grab_set()
		self.transient(master)

	def _on_ok(self) -> None:
		value = (self.entry.get() or "").strip()
		if not value:
			messagebox.showerror(tr("server"), tr("server_error_empty"), parent=self)
			return
		if not (value.startswith("http://") or value.startswith("https://")):
			messagebox.showerror(tr("server"), tr("server_error_protocol"), parent=self)
			return
		self._value = value
		self.destroy()

	def _on_cancel(self) -> None:
		self._value = None
		self.destroy()

	def get_value(self) -> str | None:
		return self._value


class LoginDialog(ctk.CTkToplevel):
	def __init__(self, master: ctk.CTk, *, initial_username: str, initial_password: str, initial_remember: bool):
		super().__init__(master)

		self.title(tr("login"))
		self.resizable(False, False)

		self._result: tuple[str, str, bool] | None = None
		self.protocol("WM_DELETE_WINDOW", self._on_cancel)

		self.grid_columnconfigure(0, weight=1)

		ctk.CTkLabel(self, text=tr("username")).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
		self.user_entry = ctk.CTkEntry(self, width=340)
		self.user_entry.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
		if initial_username:
			self.user_entry.insert(0, initial_username)

		ctk.CTkLabel(self, text=tr("password")).grid(row=2, column=0, padx=12, pady=(0, 6), sticky="w")
		self.pass_entry = ctk.CTkEntry(self, width=340, show="*")
		self.pass_entry.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
		if initial_password:
			self.pass_entry.insert(0, initial_password)

		self.remember_var = ctk.BooleanVar(value=bool(initial_remember))
		ctk.CTkCheckBox(self, text=tr("save_user"), variable=self.remember_var).grid(
			row=4, column=0, padx=12, pady=(0, 12), sticky="w"
		)

		btns = ctk.CTkFrame(self, fg_color="transparent")
		btns.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="e")

		ctk.CTkButton(btns, text=tr("cancel"), command=self._on_cancel).pack(side="right")
		ctk.CTkButton(btns, text=tr("ok"), command=self._on_ok).pack(side="right", padx=(0, 8))

		# Hotkeys
		self.bind("<Return>", lambda _e: self._on_ok())
		self.bind("<Escape>", lambda _e: self._on_cancel())

		self.after(50, self.user_entry.focus_set)
		self.grab_set()
		self.transient(master)

	def _on_ok(self) -> None:
		username = (self.user_entry.get() or "").strip()
		password = self.pass_entry.get() or ""
		remember = bool(self.remember_var.get())

		if not username:
			messagebox.showerror(tr("login"), tr("login_error_username"), parent=self)
			return
		if not password:
			messagebox.showerror(tr("login"), tr("login_error_password"), parent=self)
			return

		self._result = (username, password, remember)
		self.destroy()

	def _on_cancel(self) -> None:
		self._result = None
		self.destroy()

	def get_result(self) -> tuple[str, str, bool] | None:
		return self._result


class ConcernDialog(ctk.CTkToplevel):
	def __init__(self, master: ctk.CTk, concerns: list[dict], initial_concern_id: int | None):
		super().__init__(master)

		self.title(tr("concern"))
		self.resizable(False, False)

		self._value: int | None = None
		self._name: str | None = None
		self.protocol("WM_DELETE_WINDOW", self._on_cancel)

		# Only show open concerns, by name only
		open_concerns = [c for c in concerns if isinstance(c, dict) and c.get("closed") is False]

		self._display_to_id: dict[str, int] = {}
		self._display_to_name: dict[str, str] = {}
		values: list[str] = []
		name_counts: dict[str, int] = {}
		for c in open_concerns:
			cid = c.get("id")
			if not isinstance(cid, int):
				continue
			name = (c.get("name") or "(no name)").strip() or "(no name)"

			# Avoid collisions if multiple open concerns share the same name
			count = name_counts.get(name, 0) + 1
			name_counts[name] = count
			display = name if count == 1 else f"{name} ({count})"

			self._display_to_id[display] = cid
			self._display_to_name[display] = name
			values.append(display)

		self.grid_columnconfigure(0, weight=1)
		ctk.CTkLabel(self, text=tr("concern")).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

		self.selection_var = ctk.StringVar(value=values[0] if values else "")
		# Try to preselect the currently active concern
		if initial_concern_id is not None:
			for disp, cid in self._display_to_id.items():
				if cid == initial_concern_id:
					self.selection_var.set(disp)
					break

		self.option = ctk.CTkOptionMenu(self, values=values if values else [tr("no_open_concerns")], variable=self.selection_var)
		self.option.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

		btns = ctk.CTkFrame(self, fg_color="transparent")
		btns.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="e")
		ctk.CTkButton(btns, text=tr("cancel"), command=self._on_cancel).pack(side="right")
		ctk.CTkButton(btns, text=tr("ok"), command=self._on_ok).pack(side="right", padx=(0, 8))

		# Hotkeys
		self.bind("<Return>", lambda _e: self._on_ok())
		self.bind("<Escape>", lambda _e: self._on_cancel())

		self.after(50, self.option.focus_set)
		self.grab_set()
		self.transient(master)

	def _on_ok(self) -> None:
		selected = (self.selection_var.get() or "").strip()
		cid = self._display_to_id.get(selected)
		name = self._display_to_name.get(selected)
		if cid is None:
			messagebox.showerror(tr("concern"), tr("select_concern_error"), parent=self)
			return
		self._value = cid
		self._name = name
		self.destroy()

	def _on_cancel(self) -> None:
		self._value = None
		self._name = None
		self.destroy()

	def get_value(self) -> tuple[int, str] | None:
		if self._value is None or not self._name:
			return None
		return self._value, self._name


class DetailsDialog(ctk.CTkToplevel):
	def __init__(self, master: ctk.CTk, *, server: str, username: str, login_text: str, concern_name: str | None):
		super().__init__(master)

		self.title(tr("info"))
		self.resizable(False, False)
		self.protocol("WM_DELETE_WINDOW", self.destroy)

		self.grid_columnconfigure(0, weight=1)

		rows = [
			(tr("server"), server or "-"),
			(tr("user"), username or "-"),
			(tr("login"), login_text),
			(tr("concern"), concern_name or "-"),
		]

		for idx, (label, value) in enumerate(rows):
			ctk.CTkLabel(self, text=f"{label}:", width=90, anchor="w").grid(
				row=idx, column=0, padx=12, pady=(12 if idx == 0 else 6, 0), sticky="w"
			)
			ctk.CTkLabel(self, text=str(value), anchor="w").grid(
				row=idx, column=1, padx=(0, 12), pady=(12 if idx == 0 else 6, 0), sticky="w"
			)

		ctk.CTkButton(self, text=tr("close"), command=self.destroy).grid(row=len(rows), column=0, columnspan=2, padx=12, pady=12, sticky="e")

		# Hotkeys
		self.bind("<Return>", lambda _e: self.destroy())
		self.bind("<Escape>", lambda _e: self.destroy())

		self.grab_set()
		self.transient(master)


class RegisterPatientDialog(ctk.CTkToplevel):
	def __init__(
		self,
		master: ctk.CTk,
		*,
		server_url: str,
		cookies: dict[str, str],
		printer_name: str,
		printing_enabled: bool,
		ecard_enabled: bool,
		group_choices: list[str],
		display_to_group_id: dict[str, int],
		prefill_group_display: str,
		auto_read: bool = False,
	):
		super().__init__(master)
		self.title(tr("register_new_patient"))
		self.resizable(True, False)
		self.protocol("WM_DELETE_WINDOW", self.destroy)

		self._server_url = server_url
		self._cookies = dict(cookies or {})
		self._display_to_group_id = dict(display_to_group_id or {})
		self._printer_name = (printer_name or "").strip() or "Generic / Text Only"
		self._printing_enabled = bool(printing_enabled)
		self._ecard_enabled = bool(ecard_enabled)
		self._birth_mode: str = "picker"

		self.grid_columnconfigure(0, weight=1)

		form = ctk.CTkFrame(self)
		form.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
		form.grid_columnconfigure(0, weight=1)
		form.grid_columnconfigure(1, weight=1)
		form.grid_columnconfigure(2, weight=1)

		# Row 0: Last name / First name / Number
		ctk.CTkLabel(form, text=tr("lastname"), anchor="w").grid(row=0, column=0, padx=(0, 10), pady=(10, 4), sticky="w")
		ctk.CTkLabel(form, text=tr("firstname"), anchor="w").grid(row=0, column=1, padx=(0, 10), pady=(10, 4), sticky="w")
		ctk.CTkLabel(form, text=tr("number"), anchor="w").grid(row=0, column=2, padx=(0, 0), pady=(10, 4), sticky="w")

		self.lastname_entry = ctk.CTkEntry(form)
		self.firstname_entry = ctk.CTkEntry(form)
		self.number_entry = ctk.CTkEntry(form)
		self.lastname_entry.grid(row=1, column=0, padx=(0, 10), pady=(0, 10), sticky="ew")
		self.firstname_entry.grid(row=1, column=1, padx=(0, 10), pady=(0, 10), sticky="ew")
		self.number_entry.grid(row=1, column=2, padx=(0, 0), pady=(0, 10), sticky="ew")

		# Row 2: Insurance / Birth date / Sex
		ctk.CTkLabel(form, text=tr("insurance"), anchor="w").grid(row=2, column=0, padx=(0, 10), pady=(0, 4), sticky="w")
		ctk.CTkLabel(form, text=tr("birthdate"), anchor="w").grid(row=2, column=1, padx=(0, 10), pady=(0, 4), sticky="w")
		ctk.CTkLabel(form, text=tr("sex"), anchor="w").grid(row=2, column=2, padx=(0, 0), pady=(0, 4), sticky="w")

		self.svnr_entry = ctk.CTkEntry(form)
		self.svnr_entry.grid(row=3, column=0, padx=(0, 10), pady=(0, 14), sticky="ew")
		self.svnr_entry.bind("<FocusOut>", self._format_svnr)
		# Date picker (tkcalendar). Falls back to plain entry if tkcalendar isn't installed.
		try:
			from tkcalendar import DateEntry  # type: ignore

			self.birth_picker = DateEntry(form, date_pattern="yyyy-mm-dd")
			self.birth_picker.grid(row=3, column=1, padx=(0, 10), pady=(0, 14), sticky="w")
			self._birth_mode = "picker"
		except Exception:
			self.birth_entry = ctk.CTkEntry(form)
			self.birth_entry.grid(row=3, column=1, padx=(0, 10), pady=(0, 14), sticky="ew")
			self._birth_mode = "entry"

		self.sex_var = ctk.StringVar(value="None/Other")
		self.sex_box = ctk.CTkComboBox(form, values=["Male", "Female", "None/Other"], variable=self.sex_var, state="readonly")
		self.sex_box.grid(row=3, column=2, padx=(0, 0), pady=(0, 14), sticky="ew")
		self._setup_combobox_cycling(self.sex_box)

		# Read Ecard Button
		self.ecard_btn = ctk.CTkButton(form, text=tr("read_ecard"), command=self._on_read_ecard)
		self.ecard_btn.grid(
			row=4, column=0, columnspan=3, padx=(0, 0), pady=(0, 14), sticky="ew"
		)
		if not self._ecard_enabled:
			self.ecard_btn.configure(state="disabled")

		# Section: Treatment
		ctk.CTkLabel(form, text=tr("treatment"), font=ctk.CTkFont(size=22, weight="bold"), anchor="w").grid(
			row=5, column=0, columnspan=3, padx=(0, 0), pady=(0, 8), sticky="w"
		)
		sep = ctk.CTkFrame(form, height=2)
		sep.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 14))

		ctk.CTkLabel(form, text=tr("treatment_group"), anchor="w").grid(row=7, column=0, padx=(0, 10), pady=(0, 4), sticky="w")
		self.group_var = ctk.StringVar(value=prefill_group_display or "")
		values = [""] + list(group_choices or [])
		self.group_menu = ctk.CTkComboBox(form, values=values, variable=self.group_var, state="readonly")
		self.group_menu.grid(row=8, column=0, padx=(0, 10), pady=(0, 14), sticky="ew")
		self._setup_combobox_cycling(self.group_menu)

		# Diagnosis / Info / NACA
		ctk.CTkLabel(form, text=tr("diagnosis"), anchor="w").grid(row=9, column=0, padx=(0, 10), pady=(0, 4), sticky="w")
		ctk.CTkLabel(form, text=tr("info"), anchor="w").grid(row=9, column=1, padx=(0, 10), pady=(0, 4), sticky="w")
		ctk.CTkLabel(form, text=tr("naca"), anchor="w").grid(row=9, column=2, padx=(0, 0), pady=(0, 4), sticky="w")

		self.diagnosis_text = ctk.CTkTextbox(form, height=90)
		self.info_text = ctk.CTkTextbox(form, height=90)
		self.naca_var = ctk.StringVar(value="I")
		self.naca_menu = ctk.CTkComboBox(form, values=["I", "II", "III", "IV", "V", "VI", "VII"], variable=self.naca_var, state="readonly")

		self.diagnosis_text.grid(row=10, column=0, padx=(0, 10), pady=(0, 14), sticky="nsew")
		self.info_text.grid(row=10, column=1, padx=(0, 10), pady=(0, 14), sticky="nsew")
		self.naca_menu.grid(row=10, column=2, padx=(0, 0), pady=(0, 14), sticky="nw")
		self._setup_combobox_cycling(self.naca_menu)

		# Fix tab traversal for textboxes
		self.diagnosis_text.bind("<Tab>", lambda _e: self.info_text.focus_set() or "break")
		self.info_text.bind("<Tab>", lambda _e: self.naca_menu.focus_set() or "break")

		# Buttons
		btns = ctk.CTkFrame(form, fg_color="transparent")
		btns.grid(row=11, column=0, columnspan=3, sticky="w", pady=(0, 10))
		ctk.CTkButton(btns, text=tr("save_patient"), command=self._on_save).pack(side="left", padx=(0, 10))
		ctk.CTkButton(btns, text=tr("close"), command=self.destroy).pack(side="left")

		# Hotkeys
		self.bind("<Escape>", lambda _e: self.destroy())
		self.bind("<Control-s>", lambda _e: self._on_save())
		self.bind("<Control-S>", lambda _e: self._on_save())
		self.bind("<Return>", lambda _e: self._on_save())
		if self._ecard_enabled:
			self.bind("<Control-e>", lambda _e: self._on_read_ecard())
			self.bind("<Control-E>", lambda _e: self._on_read_ecard())

		self._setup_focus_highlight()
		self.after(50, self.lastname_entry.focus_set)
		
		if auto_read and self._ecard_enabled:
			self.after(200, self._on_read_ecard)

		self.grab_set()
		self.transient(master)

	def _setup_focus_highlight(self) -> None:
		# Get theme color (blue)
		theme_color = self.master._resolve_theme_color(ctk.ThemeManager.theme["CTkButton"]["fg_color"])
		default_border = self.master._resolve_theme_color(ctk.ThemeManager.theme["CTkEntry"]["border_color"])

		def _on_focus_in(widget) -> None:
			try:
				if hasattr(widget, "configure"):
					widget.configure(border_color=theme_color)
				elif hasattr(widget, "config"): # tk widget
					widget.config(highlightcolor=theme_color, highlightthickness=2)
			except Exception:
				pass

		def _on_focus_out(widget) -> None:
			try:
				if hasattr(widget, "configure"):
					widget.configure(border_color=default_border)
				elif hasattr(widget, "config"): # tk widget
					widget.config(highlightcolor="black", highlightthickness=0) # Reset to default
			except Exception:
				pass

		widgets = [
			self.lastname_entry, self.firstname_entry, self.number_entry,
			self.svnr_entry, self.sex_box, self.group_menu,
			self.diagnosis_text, self.info_text, self.naca_menu
		]
		if self._birth_mode == "entry":
			widgets.append(self.birth_entry)
		elif self._birth_mode == "picker":
			# DateEntry is a composite widget, we need to bind to the entry part
			try:
				widgets.append(self.birth_picker._top_cal) # Calendar popup
				# The entry part of DateEntry is usually accessible via ._entry or direct binding
				# But DateEntry inherits from Entry, so we can bind directly
				widgets.append(self.birth_picker)
			except Exception:
				pass

		for w in widgets:
			w.bind("<FocusIn>", lambda _e, w=w: _on_focus_in(w), add="+")
			w.bind("<FocusOut>", lambda _e, w=w: _on_focus_out(w), add="+")

	def _setup_combobox_cycling(self, combo: ctk.CTkComboBox) -> None:
		def _cycle(delta: int) -> str:
			values = combo._values
			if not values:
				return "break"
			current_val = combo.get()
			try:
				idx = values.index(current_val)
			except ValueError:
				idx = -1
			new_idx = (idx + delta) % len(values)
			new_val = values[new_idx]
			combo.set(new_val)
			if combo._command:
				combo._command(new_val)
			return "break"

		combo.bind("<Up>", lambda _e: _cycle(-1))
		combo.bind("<Down>", lambda _e: _cycle(1))

	def _parse_birthday(self, raw: str) -> str:
		raw = (raw or "").strip()
		if not raw or raw.lower() in {"tt. mm. jjjj", "tt.mm.jjjj"}:
			return ""
		# Accept YYYY-MM-DD
		if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
			return raw
		# Accept dd.mm.yyyy or dd. mm. yyyy
		norm = raw.replace(" ", "")
		if len(norm) == 10 and norm[2] == "." and norm[5] == ".":
			dd, mm, yyyy = norm[0:2], norm[3:5], norm[6:10]
			if dd.isdigit() and mm.isdigit() and yyyy.isdigit():
				return f"{yyyy}-{mm}-{dd}"
		return raw

	def _on_read_ecard(self) -> None:
		try:
			lastname, firstname, birthday, insurance, sex = ecard.read_data()
			now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
			scan_line = f"e-card scan: {now_text}"
			
			self.lastname_entry.delete(0, "end")
			self.lastname_entry.insert(0, lastname)
			
			self.firstname_entry.delete(0, "end")
			self.firstname_entry.insert(0, firstname)
			
			self.svnr_entry.delete(0, "end")
			self.svnr_entry.insert(0, insurance)
			
			if self._birth_mode == "picker":
				try:
					self.birth_picker.set_date(birthday)
				except Exception:
					pass
			else:
				self.birth_entry.delete(0, "end")
				self.birth_entry.insert(0, birthday)

			# ecard.read_data() normalizes sex to "Male"/"Female"/"".
			# Keep a small fallback for older/edge reader outputs.
			sex_norm = (sex or "").strip()
			if sex_norm in ["Male", "Female"]:
				self.sex_var.set(sex_norm)
			elif sex_norm.upper() in {"M", "1"}:
				self.sex_var.set("Male")
			elif sex_norm.upper() in {"F", "2"}:
				self.sex_var.set("Female")
			else:
				self.sex_var.set("None/Other")

			# Add scan timestamp to the Info field (without overwriting existing notes)
			try:
				current_info = (self.info_text.get("1.0", "end") or "").strip()
			except Exception:
				current_info = ""
			if current_info:
				self.info_text.insert("end", "\n" + scan_line)
			else:
				self.info_text.delete("1.0", "end")
				self.info_text.insert("1.0", scan_line)

		except Exception as e:
			messagebox.showerror(tr("read_ecard"), tr("read_ecard_error", e), parent=self)

	def _format_svnr(self, _event=None) -> None:
		val = (self.svnr_entry.get() or "").strip()
		if len(val) == 10 and val.isdigit():
			formatted = f"{val[:4]}/{val[4:]}"
			self.svnr_entry.delete(0, "end")
			self.svnr_entry.insert(0, formatted)

	def _on_save(self) -> None:
		lastname = (self.lastname_entry.get() or "").strip()
		firstname = (self.firstname_entry.get() or "").strip()
		external_id = (self.number_entry.get() or "").strip()
		insurance = (self.svnr_entry.get() or "").strip()
		birthday = ""
		if self._birth_mode == "picker":
			try:
				birthday = self.birth_picker.get_date().isoformat()  # type: ignore[attr-defined]
			except Exception:
				birthday = ""
		else:
			birthday = self._parse_birthday(self.birth_entry.get() or "")  # type: ignore[attr-defined]
		
		sex_raw = self.sex_var.get()
		sex = "" if sex_raw == "None/Other" else sex_raw
		naca = self.naca_var.get() or "I"
		diagnosis = (self.diagnosis_text.get("1.0", "end") or "").strip()
		info = (self.info_text.get("1.0", "end") or "").strip()
		group_display = (self.group_var.get() or "").strip()

		# Required: name + group only
		if not lastname:
			messagebox.showerror(tr("save_patient"), tr("save_patient_error_lastname"), parent=self)
			return
		if not firstname:
			messagebox.showerror(tr("save_patient"), tr("save_patient_error_firstname"), parent=self)
			return

		group_id = self._display_to_group_id.get(group_display) if group_display else None
		if not isinstance(group_id, int):
			messagebox.showerror(tr("save_patient"), tr("save_patient_error_group"), parent=self)
			return

		try:
			patient = Patient(
				firstname=firstname,
				lastname=lastname,
				group_id=group_id,
				group_name=group_display,
				external_id=external_id,
				naca=naca,
				sex=sex,
				info=info,
				diagnosis=diagnosis,
				insurance=insurance,
				birthday=birthday,
			)
		except Exception as e:
			messagebox.showerror(tr("save_patient"), tr("save_patient_error_invalid", e), parent=self)
			return

		try:
			result = PatAdmin.register(self._server_url, self._cookies, patient.to_payload())
		except Exception as e:
			messagebox.showerror(tr("save_patient"), tr("save_patient_error_registration", e), parent=self)
			return

		if not result.get("ok"):
			status = result.get("status")
			text = result.get("text")
			messagebox.showerror(tr("save_patient"), tr("save_patient_error_status", status, text), parent=self)
			return

		patient_id = result.get("patient_id")
		if not isinstance(patient_id, int):
			# Fallback: try to find patient by name
			try:
				patient_id = PatAdmin.get_patient_id_by_name(self._server_url, self._cookies, lastname)
			except Exception:
				pass

		if not isinstance(patient_id, int):
			messagebox.showinfo(tr("save_patient"), tr("save_patient_success_no_id"), parent=self)
			self.destroy()
			return

		# Print immediately after successful registration
		if self._printing_enabled:
			try:
				print_util.PatPrint(
					self._printer_name,
					patient,
					patient_id=patient_id,
					group_name=group_display,
					base_url=self._server_url,
				)
			except Exception as e:
				messagebox.showerror(tr("printing"), tr("print_error", patient_id, e), parent=self)
				self.destroy()
				return

		# Notification instead of dialog
		try:
			import subprocess
			title = f"{lastname}, {firstname}"
			body = f"{group_display} & {naca}"
			# Escape for PowerShell
			safe_title = title.replace('"', "'").replace('$', '`$')
			safe_body = body.replace('"', "'").replace('$', '`$')
			
			ps_script = f"""
			[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
			$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
			$textNodes = $template.GetElementsByTagName("text")
			$textNodes.item(0).AppendChild($template.CreateTextNode("{safe_title}")) > $null
			$textNodes.item(1).AppendChild($template.CreateTextNode("{safe_body}")) > $null
			$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("PatAdmin FlowReg")
			$notification = [Windows.UI.Notifications.ToastNotification]::new($template)
			$notifier.Show($notification)
			"""
			subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_script], creationflags=0x08000000) # CREATE_NO_WINDOW
		except Exception:
			pass

		self.destroy()


class App(ctk.CTk):
	def __init__(self) -> None:
		super().__init__()

		self.app_state = load_saved_credentials()
		self.settings = load_settings()

		_translator.load_language(self.settings.language)

		ctk.set_appearance_mode(self.settings.appearance_mode)
		
		self._ensure_custom_themes()
		self._apply_theme(self.settings.theme)

		self.title("PatAdmin FlowReg")
		self.geometry("980x640")
		if self.settings.fullscreen:
			self.attributes("-fullscreen", True)

		self._cached_groups: list[dict] = []
		self._cached_counts: dict[int, int] = {}
		self._group_display_to_id: dict[str, int] = {}
		self._auto_refresh_after_id: str | None = None
		self._clock_after_id: str | None = None
		self._next_refresh_time: datetime.datetime | None = None
		self._paused: bool = False
		self._current_register_dialog: RegisterPatientDialog | None = None

		# Start e-card monitor thread
		self._ecard_thread_running = True
		self._ecard_thread = threading.Thread(target=self._monitor_ecard_loop, daemon=True)
		self._ecard_thread.start()

		self._build_menu()
		self._build_main()
		self._refresh_status()
		self._schedule_auto_refresh()

	def _ensure_custom_themes(self) -> None:
		theme_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")
		if not os.path.exists(theme_dir):
			os.makedirs(theme_dir)
		
		# Try to load base 'blue' theme to generate others
		try:
			# load_theme sets ThemeManager.theme but returns None
			ctk.ThemeManager.load_theme("blue")
			base = ctk.ThemeManager.theme
		except Exception:
			return

		if not isinstance(base, dict):
			return

		# Define new themes with color replacements for Blue's colors
		# Blue Primary: #3B8ED0, Dark: #1F6AA5
		# Blue Hover: #36719F, Dark: #144870
		new_themes = {
			"red": [
				("#3B8ED0", "#E74C3C"), ("#1F6AA5", "#C0392B"), 
				("#36719F", "#C0392B"), ("#144870", "#922B21")
			],
			"violet": [
				("#3B8ED0", "#9B59B6"), ("#1F6AA5", "#8E44AD"), 
				("#36719F", "#8E44AD"), ("#144870", "#6C3483")
			]
		}

		import copy
		for name, replacements in new_themes.items():
			path = os.path.join(theme_dir, f"{name}.json")
			# Always regenerate to ensure validity (fixes empty/null files)
			new_theme = copy.deepcopy(base)
			
			def replace_recursive(item):
				if isinstance(item, dict):
					for k, v in item.items():
						item[k] = replace_recursive(v)
				elif isinstance(item, list):
					for i, v in enumerate(item):
						item[i] = replace_recursive(v)
				elif isinstance(item, str):
					for old, new in replacements:
						if item.lower() == old.lower():
							return new
				return item
			
			replace_recursive(new_theme)
			with open(path, "w") as f:
				json.dump(new_theme, f, indent=2)

	def _apply_theme(self, theme_name: str) -> None:
		if theme_name in ["blue", "green", "dark-blue"]:
			ctk.set_default_color_theme(theme_name)
		else:
			path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes", f"{theme_name}.json")
			if os.path.exists(path):
				ctk.set_default_color_theme(path)
			else:
				# Fallback
				ctk.set_default_color_theme("blue")

	def _build_menu(self) -> None:
		menubar = Menu(self)
		self._setup_menu = Menu(menubar, tearoff=0)
		self._setup_menu.add_command(label=tr("server"), command=self._setup_server, accelerator="Ctrl+Alt+S")
		self._setup_menu.add_command(label=tr("login"), command=self._setup_login, accelerator="Ctrl+Alt+L")
		self._setup_menu.add_command(label=tr("concern"), command=self._setup_concern, accelerator="Ctrl+Alt+C")
		self._setup_menu.add_command(label=tr("treatment"), command=self._setup_details, accelerator="Ctrl+Alt+D")
		menubar.add_cascade(label=tr("setup"), menu=self._setup_menu)

		# Options menu
		self._options_menu = Menu(menubar, tearoff=0)
		self._printing_var = tk.BooleanVar(value=bool(self.settings.printing_enabled))
		self._auto_refresh_var = tk.BooleanVar(value=bool(self.settings.auto_refresh_enabled))
		self._ecard_var = tk.BooleanVar(value=bool(self.settings.ecard_enabled))
		self._options_menu.add_checkbutton(label=tr("printing"), variable=self._printing_var, command=self._toggle_printing, accelerator="Ctrl+Alt+P")
		self._options_menu.add_checkbutton(label=tr("auto_refresh"), variable=self._auto_refresh_var, command=self._toggle_auto_refresh, accelerator="Ctrl+Alt+R")
		self._options_menu.add_checkbutton(label=tr("ecard_reading"), variable=self._ecard_var, command=self._toggle_ecard, accelerator="Ctrl+Alt+E")
		menubar.add_cascade(label=tr("options"), menu=self._options_menu)

		# Display menu
		self._display_menu = Menu(menubar, tearoff=0)
		
		# Fullscreen
		self._fullscreen_var = tk.BooleanVar(value=bool(self.settings.fullscreen))
		self._display_menu.add_checkbutton(label=tr("fullscreen"), variable=self._fullscreen_var, command=self._toggle_fullscreen, accelerator="F11")
		self._display_menu.add_separator()

		# Theme
		self._theme_menu = Menu(self._display_menu, tearoff=0)
		self._theme_var = tk.StringVar(value=self.settings.theme)
		for t in ["blue", "green", "dark-blue", "red", "violet"]:
			self._theme_menu.add_radiobutton(label=t.title(), variable=self._theme_var, value=t, command=self._set_theme)
		self._display_menu.add_cascade(label=tr("theme"), menu=self._theme_menu)

		# Appearance Mode
		self._appearance_menu = Menu(self._display_menu, tearoff=0)
		self._appearance_var = tk.StringVar(value=self.settings.appearance_mode)
		for m in ["System", "Dark", "Light"]:
			self._appearance_menu.add_radiobutton(label=m, variable=self._appearance_var, value=m, command=self._set_appearance_mode)
		self._display_menu.add_cascade(label=tr("appearance_mode"), menu=self._appearance_menu)

		# Language
		self._language_menu = Menu(self._display_menu, tearoff=0)
		self._language_var = tk.StringVar(value=self.settings.language)
		for lang_code, lang_name in _translator.get_available_languages():
			self._language_menu.add_radiobutton(label=lang_name, variable=self._language_var, value=lang_code, command=self._set_language)
		self._display_menu.add_cascade(label=tr("language"), menu=self._language_menu)

		menubar.add_cascade(label=tr("display"), menu=self._display_menu)

		# Settings menu
		self._settings_menu = Menu(menubar, tearoff=0)
		self._settings_menu.add_command(label=tr("settings") + "...", command=self._open_settings, accelerator="Ctrl+Alt+T")
		menubar.add_cascade(label=tr("settings"), menu=self._settings_menu)

		self.config(menu=menubar)
		self._bind_hotkeys()

	def _bind_hotkeys(self) -> None:
		# Setup
		self.bind_all("<Control-Alt-s>", lambda _e: self._setup_server())
		self.bind_all("<Control-Alt-l>", lambda _e: self._setup_login())
		self.bind_all("<Control-Alt-c>", lambda _e: self._setup_concern())
		self.bind_all("<Control-Alt-d>", lambda _e: self._setup_details())

		# Options toggles
		self.bind_all("<Control-Alt-p>", lambda _e: self._hotkey_toggle(self._printing_var, self._toggle_printing))
		self.bind_all("<Control-Alt-r>", lambda _e: self._hotkey_toggle(self._auto_refresh_var, self._toggle_auto_refresh))
		self.bind_all("<Control-Alt-e>", lambda _e: self._hotkey_toggle(self._ecard_var, self._toggle_ecard))

		# Display toggles
		self.bind_all("<F11>", lambda _e: self._hotkey_toggle(self._fullscreen_var, self._toggle_fullscreen))

		# Settings
		self.bind_all("<Control-Alt-t>", lambda _e: self._open_settings())

		# Global register (works when list is visible)
		self.bind_all("<Control-n>", lambda _e: self._open_register(None, ""))
		self.bind_all("<Control-N>", lambda _e: self._open_register(None, ""))

	def _monitor_ecard_loop(self) -> None:
		"""
		Background thread to monitor for e-card insertion.
		"""
		was_present = False
		while getattr(self, "_ecard_thread_running", True):
			if not self.settings.ecard_enabled:
				time.sleep(2.0)
				continue

			try:
				present = ecard.is_card_present()
				if present and not was_present:
					# Card just inserted
					self.after(0, self._on_card_inserted)
				was_present = present
			except Exception:
				pass
			
			time.sleep(0.5)

	def _on_card_inserted(self) -> None:
		"""
		Called on main thread when a card is detected.
		"""
		# If e-card is disabled in settings, do nothing
		if not self.settings.ecard_enabled:
			return

		# If we are already in a register dialog, just bring it to front
		if self._current_register_dialog and self._current_register_dialog.winfo_exists():
			self._current_register_dialog.lift()
			# self._current_register_dialog.focus_force() # Optional: force focus
			return

		# If we are not logged in or have no concern, we can't register properly,
		# but maybe we should show a warning or just ignore?
		# The _open_register method checks for login/concern and shows error if missing.
		# So we can just call it.
		
		# We don't know which group to preselect, so pass None.
		# Pass auto_read=False so it doesn't read immediately, just opens the form.
		self._open_register(None, "", auto_read=False)

	def _hotkey_toggle(self, var: tk.BooleanVar, fn) -> None:
		try:
			var.set(not bool(var.get()))
		except Exception:
			pass
		fn()

	def _toggle_fullscreen(self) -> None:
		state = bool(self._fullscreen_var.get())
		self.attributes("-fullscreen", state)
		self.settings.fullscreen = state
		try:
			save_settings(self.settings)
		except Exception:
			pass

	def _set_theme(self) -> None:
		theme = self._theme_var.get()
		self._apply_theme(theme)
		self.settings.theme = theme
		try:
			save_settings(self.settings)
		except Exception:
			pass
		
		# Rebuild UI to apply theme, using cached data to avoid fetch
		self._build_main(use_cache=True)

	def _set_appearance_mode(self) -> None:
		mode = self._appearance_var.get()
		ctk.set_appearance_mode(mode)
		self.settings.appearance_mode = mode
		try:
			save_settings(self.settings)
		except Exception:
			pass
		
		# Refresh content to update canvas colors etc. AND fetch fresh data
		self._refresh_main_content(quiet=True, use_cache=False)

	def _set_language(self) -> None:
		lang = self._language_var.get()
		if lang == self.settings.language:
			return
		self.settings.language = lang
		_translator.load_language(lang)
		try:
			save_settings(self.settings)
		except Exception:
			pass
		
		self._build_menu()
		self._build_main(use_cache=True)

	def _toggle_printing(self) -> None:
		self.settings.printing_enabled = bool(self._printing_var.get())
		try:
			save_settings(self.settings)
		except Exception as e:
			messagebox.showerror(tr("options"), tr("options_save_error", e), parent=self)

	def _toggle_auto_refresh(self) -> None:
		self.settings.auto_refresh_enabled = bool(self._auto_refresh_var.get())
		try:
			save_settings(self.settings)
		except Exception as e:
			messagebox.showerror(tr("options"), tr("options_save_error", e), parent=self)
		self._schedule_auto_refresh()

	def _toggle_ecard(self) -> None:
		self.settings.ecard_enabled = bool(self._ecard_var.get())
		try:
			save_settings(self.settings)
		except Exception as e:
			messagebox.showerror(tr("options"), tr("options_save_error", e), parent=self)

	def _schedule_auto_refresh(self) -> None:
		# Cancel existing schedule
		if self._auto_refresh_after_id is not None:
			try:
				self.after_cancel(self._auto_refresh_after_id)
			except Exception:
				pass
			self._auto_refresh_after_id = None
		
		self._next_refresh_time = None

		if not bool(self.settings.auto_refresh_enabled):
			return

		if not self._has_active_concern():
			return

		interval_sec = max(2, int(self.settings.refresh_interval_sec))
		interval_ms = interval_sec * 1000
		
		self._next_refresh_time = datetime.datetime.now() + datetime.timedelta(seconds=interval_sec)
		self._auto_refresh_after_id = self.after(interval_ms, self._auto_refresh_tick)

	def _auto_refresh_tick(self) -> None:
		try:
			if not self._paused and self._has_active_concern() and bool(self.settings.auto_refresh_enabled):
				self._refresh_main_content(quiet=True)
		except Exception:
			pass
		finally:
			self._schedule_auto_refresh()

	def _open_settings(self) -> None:
		dlg = SettingsDialog(self, settings=self.settings)
		self.wait_window(dlg)
		new_settings = dlg.get_value()
		if new_settings is None:
			return
		# Preserve toggles from Options menu
		new_settings.printing_enabled = bool(self.settings.printing_enabled)
		new_settings.auto_refresh_enabled = bool(self.settings.auto_refresh_enabled)
		new_settings.ecard_enabled = bool(self.settings.ecard_enabled)
		# Preserve Display settings
		new_settings.fullscreen = bool(self.settings.fullscreen)
		new_settings.theme = str(self.settings.theme)
		new_settings.appearance_mode = str(self.settings.appearance_mode)
		new_settings.language = str(self.settings.language)
		
		self.settings = new_settings
		# Update menu checkbox vars
		try:
			self._printing_var.set(bool(self.settings.printing_enabled))
			self._auto_refresh_var.set(bool(self.settings.auto_refresh_enabled))
			self._ecard_var.set(bool(self.settings.ecard_enabled))
		except Exception:
			pass
		self._schedule_auto_refresh()
		try:
			save_settings(self.settings)
		except Exception as e:
			messagebox.showerror(tr("settings"), tr("options_save_error", e), parent=self)

	def _build_main(self, use_cache: bool = False) -> None:
		# Cleanup existing frames if rebuilding (e.g. theme change)
		if hasattr(self, "_header_frame") and self._header_frame:
			try:
				self._header_frame.destroy()
			except Exception:
				pass
		if hasattr(self, "_content_frame") and self._content_frame:
			try:
				self._content_frame.destroy()
			except Exception:
				pass
		if hasattr(self, "_footer_frame") and self._footer_frame:
			try:
				self._footer_frame.destroy()
			except Exception:
				pass

		self.grid_columnconfigure(0, weight=1)
		self.grid_rowconfigure(0, weight=0) # Header
		self.grid_rowconfigure(1, weight=1) # Content
		self.grid_rowconfigure(2, weight=0) # Footer

		# Header
		self._header_frame = ctk.CTkFrame(self, height=40, corner_radius=0)
		self._header_frame.grid(row=0, column=0, sticky="ew")
		self._header_frame.grid_columnconfigure(0, weight=1)
		
		self._header_label = ctk.CTkLabel(self._header_frame, text="", font=ctk.CTkFont(size=16, weight="bold"))
		self._header_label.grid(row=0, column=0, padx=16, pady=8)

		# Content
		self._content_frame = ctk.CTkFrame(self, corner_radius=0)
		self._content_frame.grid(row=1, column=0, padx=0, pady=0, sticky="nsew")
		self._content_frame.grid_columnconfigure(0, weight=1)
		self._content_frame.grid_rowconfigure(0, weight=0) # Global button
		self._content_frame.grid_rowconfigure(1, weight=1) # Scrollable list

		# Footer
		self._footer_frame = ctk.CTkFrame(self, height=24, corner_radius=0, fg_color="transparent")
		self._footer_frame.grid(row=2, column=0, sticky="ew")
		
		self._footer_status_label = ctk.CTkLabel(self._footer_frame, text="", font=ctk.CTkFont(size=12), text_color="gray")
		self._footer_status_label.pack(side="left", padx=16, pady=(0, 5))
		
		self._footer_label = ctk.CTkLabel(self._footer_frame, text="", font=ctk.CTkFont(size=12), text_color="gray")
		self._footer_label.pack(side="right", padx=16, pady=(0, 5))

		# Start clock if not running
		if self._clock_after_id is None:
			self._update_timers()

		# Main content is intentionally blank unless logged in + concern is set.
		self._refresh_main_content(use_cache=use_cache)

	def _update_timers(self) -> None:
		# Cancel previous if any (though usually this is called by self.after)
		if self._clock_after_id is not None:
			try:
				self.after_cancel(self._clock_after_id)
			except Exception:
				pass
			self._clock_after_id = None

		try:
			now = datetime.datetime.now()
			date_str = now.strftime("%d.%m.%Y")
			time_str = now.strftime("%H:%M")
			concern = self.app_state.active_concern_name or "No Concern"
			
			text = f"{concern}  |  {date_str}  |  {time_str}"
			if hasattr(self, "_header_label") and self._header_label.winfo_exists():
				self._header_label.configure(text=text)

			# Footer status (left)
			if hasattr(self, "_footer_status_label") and self._footer_status_label.winfo_exists():
				server = (self.app_state.server_url or "").strip()
				if not server:
					status_text = tr("no_server")
				elif not self.app_state.jsessionid:
					status_text = tr("not_logged_in_status", server)
				elif not self._has_active_concern():
					status_text = tr("logged_in_status", server)
				else:
					status_text = tr("connected_status", server)
				self._footer_status_label.configure(text=status_text)

			# Footer countdown (right)
			if hasattr(self, "_footer_label") and self._footer_label.winfo_exists():
				if not self.settings.auto_refresh_enabled:
					self._footer_label.configure(text=tr("paused"))
				elif not self._has_active_concern():
					self._footer_label.configure(text=tr("paused_no_concern"))
				elif self._next_refresh_time:
					remaining = (self._next_refresh_time - now).total_seconds()
					if remaining > 0:
						self._footer_label.configure(text=tr("refresh_in", int(remaining)))
					else:
						self._footer_label.configure(text=tr("refreshing"))
				else:
					self._footer_label.configure(text="")

		except Exception:
			pass
		
		self._clock_after_id = self.after(1000, self._update_timers)

	def _clear_main_content(self) -> None:
		for child in list(self._content_frame.winfo_children()):
			try:
				child.destroy()
			except Exception:
				pass

	def _has_active_concern(self) -> bool:
		cookies = self.app_state.cookies
		if not self.app_state.jsessionid or not cookies or not isinstance(cookies, dict):
			return False
		return bool(cookies.get("JSESSIONID")) and bool(cookies.get("concern"))

	def _get_active_patient_counts_by_group(self) -> dict[int, int]:
		"""Fetch active patients once and return counts keyed by group id."""
		base_url = (self.app_state.server_url or "").rstrip("/") + "/"
		endpoint = urljoin(base_url, "data/patadmin/registration/patients")
		cookies = dict(self.app_state.cookies or {})
		PatAdmin._require_cookie(cookies, "JSESSIONID")
		PatAdmin._require_cookie(cookies, "concern")

		resp = requests.get(endpoint, params={"f": "lastname", "q": ""}, cookies=cookies, timeout=15)
		resp.raise_for_status()
		payload = resp.json()
		patients = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
		if not isinstance(patients, list):
			return {}

		counts: dict[int, int] = {}
		for p in patients:
			if not isinstance(p, dict):
				continue
			gid = p.get("group")
			if isinstance(gid, int):
				counts[gid] = counts.get(gid, 0) + 1
		return counts

	def _resolve_theme_color(self, ctk_color: str | tuple[str, str] | list[str]) -> str:
		"""Resolve a CustomTkinter theme color (light/dark tuple) to a concrete tk color."""
		mode = (ctk.get_appearance_mode() or "Dark").lower()
		is_dark = "dark" in mode
		if isinstance(ctk_color, (tuple, list)) and len(ctk_color) >= 2:
			return str(ctk_color[1] if is_dark else ctk_color[0])
		return str(ctk_color)

	def _draw_capacity_icons(
		self,
		canvas: tk.Canvas,
		*,
		patients: int,
		capacity: int | None,
		width: int = 520,
		height: int = 22,
	) -> None:
		canvas.delete("all")
		canvas.configure(width=width, height=height)

		patients = max(0, int(patients))
		slots = patients if capacity is None else max(patients, int(capacity))
		if slots <= 0:
			return

		pad = 2
		gap = 2
		usable_w = max(1, width - 2 * pad)
		# Pack icons tightly from the left. Compute a size that fits all icons into the available width.
		# icon_total = slots*size + (slots-1)*gap <= usable_w
		max_size = 14
		min_size = 6
		if slots == 1:
			size = max_size
		else:
			size = int((usable_w - (slots - 1) * gap) / slots)
			size = max(min_size, min(max_size, size))
		cy = height // 2
		y0 = int(cy - size / 2)
		y1 = y0 + size

		for i in range(slots):
			x0 = int(pad + i * (size + gap))
			x1 = x0 + size

			if i < patients:
				# Red square = occupied patient
				canvas.create_rectangle(x0, y0, x1, y1, fill="red", outline="red")
			elif capacity is not None and i < int(capacity):
				# Green circle = free space (only meaningful if capacity is set)
				canvas.create_oval(x0, y0, x1, y1, fill="green", outline="green")
			else:
				# No capacity info and no patient -> draw nothing
				pass

	def _refresh_main_content(self, *, quiet: bool = False, use_cache: bool = False) -> None:
		self._clear_main_content()

		server = (self.app_state.server_url or "").strip()
		if not server:
			ctk.CTkLabel(
				self._content_frame,
				text=tr("no_server_set"),
				anchor="center",
			).grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
			return

		if not self.app_state.jsessionid:
			ctk.CTkLabel(
				self._content_frame,
				text=tr("not_logged_in"),
				anchor="center",
			).grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
			return

		# Logged in, but concern might not be set yet.
		if not self._has_active_concern():
			ctk.CTkLabel(
				self._content_frame,
				text=tr("no_concern_selected"),
				anchor="center",
			).grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
			return

		groups = []
		counts = {}

		if use_cache and self._cached_groups:
			groups = self._cached_groups
			counts = self._cached_counts
		else:
			try:
				groups = PatAdmin.get_treatment_groups(self.app_state.server_url, self.app_state.cookies or {})
				counts = self._get_active_patient_counts_by_group()
				self._cached_groups = [g for g in (groups or []) if isinstance(g, dict)]
				self._cached_counts = counts
			except Exception as e:
				if use_cache: # Fallback to cache if fetch fails?
					groups = self._cached_groups
					counts = self._cached_counts
				elif not quiet:
					messagebox.showerror(tr("treatment_group"), tr("groups_error", e), parent=self)
					return
				else:
					return

		# Cache groups for register dialog
		self._cached_groups = [g for g in (groups or []) if isinstance(g, dict)]
		self._group_display_to_id = {}
		group_displays: list[str] = []
		name_counts: dict[str, int] = {}
		for g in self._cached_groups:
			gid = g.get("id")
			if not isinstance(gid, int):
				continue
			name = (g.get("call") or g.get("name") or f"Group {gid}")
			if not isinstance(name, str) or not name.strip():
				name = f"Group {gid}"
			name = name.strip()
			count = name_counts.get(name, 0) + 1
			name_counts[name] = count
			display = name if count == 1 else f"{name} ({count})"
			self._group_display_to_id[display] = gid
			group_displays.append(display)

		scroll = ctk.CTkScrollableFrame(self._content_frame)
		scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=(6, 12))
		scroll.grid_columnconfigure(0, weight=1)

		# Global register button (addition, not replacement for inline buttons)
		# Placed outside scroll frame (Row 0)
		ctk.CTkButton(
			self._content_frame,
			text=tr("register_new_patient"),
			height=40,
			font=ctk.CTkFont(size=16, weight="bold"),
			command=lambda: self._open_register(None, ""),
		).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")

		for idx, group in enumerate(groups or []):
			if not isinstance(group, dict):
				continue
			gid = group.get("id")
			if not isinstance(gid, int):
				continue

			# Use cached display names so register dialog can map back to group id.
			# Find the display string for this gid.
			gname = None
			for disp, did in self._group_display_to_id.items():
				if did == gid:
					gname = disp
					break
			if not gname:
				gname = f"Group {gid}"

			capacity = PatAdmin.get_group_capacity(self.app_state.server_url, self.app_state.cookies or {}, gid)
			patient_count = int(counts.get(gid, 0))

			row = ctk.CTkFrame(scroll)
			row.grid(row=idx + 1, column=0, sticky="ew", padx=6, pady=6)
			row.grid_columnconfigure(1, weight=1)

			ctk.CTkLabel(row, text=gname, width=120, anchor="w").grid(row=0, column=0, padx=(10, 10), pady=10, sticky="w")

			# Capacity visualization
			# Match the canvas background to the current CTk theme/frame color
			frame_bg = self._resolve_theme_color(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
			canvas = tk.Canvas(row, highlightthickness=0, bd=0, bg=frame_bg)
			canvas.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="ew")
			self._draw_capacity_icons(canvas, patients=patient_count, capacity=capacity)

			# Occupancy text to the right of the indicators: e.g. "10% (1/10)"
			if isinstance(capacity, int) and capacity > 0:
				pct = int(round((patient_count * 100) / capacity))
				occ_text = f"{pct}% ({patient_count}/{capacity})"
			else:
				occ_text = f"- % ({patient_count}/?)"
			ctk.CTkLabel(row, text=occ_text, width=110, anchor="e").grid(
				row=0, column=2, padx=(0, 10), pady=10, sticky="e"
			)

			btn = ctk.CTkButton(
				row,
				text=tr("register_new_patient_at", gname),
				command=lambda gid=gid, name=gname: self._open_register(gid, name),
				width=260,
			)
			btn.grid(row=0, column=3, padx=(0, 10), pady=10, sticky="e")

	def _open_register(self, group_id: int | None, group_display: str, auto_read: bool = False) -> None:
		if not self._has_active_concern():
			messagebox.showerror(tr("register_new_patient"), tr("register_error_login"), parent=self)
			return

		choices = list(self._group_display_to_id.keys())
		dlg = RegisterPatientDialog(
			self,
			server_url=self.app_state.server_url,
			cookies=self.app_state.cookies or {},
			printer_name=self.settings.printer_name,
			printing_enabled=self.settings.printing_enabled,
			ecard_enabled=self.settings.ecard_enabled,
			group_choices=choices,
			display_to_group_id=self._group_display_to_id,
			prefill_group_display=(group_display if group_id is not None else ""),
			auto_read=auto_read,
		)
		self._paused = True
		self._current_register_dialog = dlg
		try:
			self.wait_window(dlg)
		finally:
			self._current_register_dialog = None
			self._paused = False
		# Refresh list after closing (patient counts/capacity may change)
		self._refresh_main_content(quiet=True)

	def _refresh_status(self) -> None:
		# Enable/disable concern menu depending on login state
		try:
			self._setup_menu.entryconfig("Concern", state="normal" if self.app_state.jsessionid else "disabled")
		except Exception:
			pass

		# Update main content if login/concern state changed
		try:
			self._refresh_main_content(quiet=False)
		except Exception:
			pass
		
		self._schedule_auto_refresh()
		self._schedule_auto_refresh()

	def _setup_details(self) -> None:
		server = self.app_state.server_url.strip() if self.app_state.server_url else ""
		user = self.app_state.username.strip() if self.app_state.username else ""
		if self.app_state.jsessionid and self.app_state.cookies:
			login_text = tr("ok")
		elif self.app_state.jsessionid and not self.app_state.cookies:
			login_text = tr("ok") + " (" + tr("no_concern_selected") + ")"
		else:
			login_text = tr("not_logged_in")

		dlg = DetailsDialog(
			self,
			server=server,
			username=user,
			login_text=login_text,
			concern_name=self.app_state.active_concern_name,
		)
		self.wait_window(dlg)

	def _setup_server(self) -> None:
		dialog = ServerDialog(self, self.app_state.server_url)
		self.wait_window(dialog)
		value = dialog.get_value()
		if value is None:
			return

		self.app_state.server_url = value
		try:
			save_server_only(value)
		except OSError as e:
			messagebox.showerror(tr("server"), tr("server_save_error", e), parent=self)
		self._refresh_status()

	def _setup_login(self) -> None:
		if not self.app_state.server_url:
			messagebox.showerror(tr("login"), tr("no_server_set"), parent=self)
			return

		dialog = LoginDialog(
			self,
			initial_username=self.app_state.username,
			initial_password="",
			initial_remember=self.app_state.remember,
		)
		self.wait_window(dialog)
		result = dialog.get_result()
		if result is None:
			return

		username, password, remember = result
		self.app_state.username = username
		self.app_state.remember = remember

		# Try to log in immediately
		self.app_state.jsessionid = None
		self.app_state.cookies = None
		self.app_state.active_concern_name = None
		self._refresh_status()
		self.update_idletasks()

		try:
			jsessionid = coceso_login(self.app_state.server_url, username, password)
			if not jsessionid:
				messagebox.showerror(tr("login"), tr("login_failed_creds"), parent=self)
				return

			# Do NOT set a concern automatically; user must choose via Setup -> Concern
			self.app_state.jsessionid = jsessionid
			self.app_state.cookies = None
			self.app_state.active_concern_name = None

		except Exception as e:
			messagebox.showerror(tr("login"), tr("login_failed", e), parent=self)
			return
		finally:
			self._refresh_status()

		if remember:
			try:
				save_credentials(self.app_state.server_url, username)
			except OSError as e:
				messagebox.showerror(tr("login"), tr("credentials_save_error", e), parent=self)

		messagebox.showinfo(tr("login"), tr("login_success"), parent=self)

	def _setup_concern(self) -> None:
		if not self.app_state.server_url:
			messagebox.showerror(tr("concern"), tr("no_server_set"), parent=self)
			return
		if not self.app_state.jsessionid:
			messagebox.showerror(tr("concern"), tr("not_logged_in"), parent=self)
			return

		try:
			concerns = get_concerns(self.app_state.server_url, self.app_state.jsessionid)
		except Exception as e:
			messagebox.showerror(tr("concern"), tr("concern_load_error", e), parent=self)
			return

		open_concerns = [c for c in concerns if isinstance(c, dict) and c.get("closed") is False]
		if not open_concerns:
			messagebox.showerror(tr("concern"), tr("concern_no_open"), parent=self)
			return

		initial_concern_id: int | None = None
		if self.app_state.cookies and isinstance(self.app_state.cookies, dict):
			raw = self.app_state.cookies.get("concern")
			try:
				initial_concern_id = int(raw) if raw is not None else None
			except Exception:
				initial_concern_id = None

		dialog = ConcernDialog(self, open_concerns, initial_concern_id)
		self.wait_window(dialog)
		result = dialog.get_value()
		if result is None:
			return
		concern_id, concern_name = result

		try:
			cookies = set_active_concern(self.app_state.server_url, self.app_state.jsessionid, concern_id)
			self.app_state.cookies = cookies
			self.app_state.active_concern_name = concern_name
			self._refresh_status()
			messagebox.showinfo(tr("concern"), tr("concern_set", concern_name), parent=self)
		except Exception as e:
			messagebox.showerror(tr("concern"), tr("concern_set_error", e), parent=self)

	def destroy(self) -> None:
		self._ecard_thread_running = False
		super().destroy()


class SettingsDialog(ctk.CTkToplevel):
	def __init__(self, master: ctk.CTk, *, settings: AppSettings):
		super().__init__(master)
		self.settings = settings or AppSettings()
		self.title(tr("settings_title"))
		self.resizable(False, False)
		self.protocol("WM_DELETE_WINDOW", self._on_cancel)

		self._value: AppSettings | None = None
		current = settings or AppSettings()

		self.grid_columnconfigure(0, weight=1)

		ctk.CTkLabel(self, text=tr("printer_escpos")).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
		ctk.CTkLabel(self, text=tr("printer_escpos_hint")).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

		printers = self._list_printers_windows()
		self.printer_var = ctk.StringVar(value=current.printer_name)
		self.printer_box = ctk.CTkComboBox(self, values=printers if printers else [current.printer_name], variable=self.printer_var, width=420)
		self.printer_box.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
		try:
			self.printer_box.set(current.printer_name)
		except Exception:
			pass

		ctk.CTkLabel(self, text=tr("refresh_interval")).grid(row=3, column=0, padx=12, pady=(0, 6), sticky="w")
		self.refresh_entry = ctk.CTkEntry(self, width=120)
		self.refresh_entry.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="w")
		self.refresh_entry.insert(0, str(int(current.refresh_interval_sec)))

		btns = ctk.CTkFrame(self, fg_color="transparent")
		btns.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="e")
		ctk.CTkButton(btns, text=tr("cancel"), command=self._on_cancel).pack(side="right")
		ctk.CTkButton(btns, text=tr("ok"), command=self._on_ok).pack(side="right", padx=(0, 8))

		# Hotkeys
		self.bind("<Return>", lambda _e: self._on_ok())
		self.bind("<Escape>", lambda _e: self._on_cancel())

		self.after(50, self.printer_box.focus_set)
		self.grab_set()
		self.transient(master)

	def _list_printers_windows(self) -> list[str]:
		# Try win32print if available, else fallback to PowerShell.
		try:
			import win32print  # type: ignore

			flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
			printers = win32print.EnumPrinters(flags)
			names = [p[2] for p in printers if len(p) >= 3 and isinstance(p[2], str) and p[2].strip()]
			return sorted(set(names))
		except Exception:
			pass
		try:
			out = subprocess.check_output(
				["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
				text=True,
				errors="ignore",
			)
			names = [ln.strip() for ln in out.splitlines() if ln.strip()]
			return sorted(set(names))
		except Exception:
			return []

	def _on_ok(self) -> None:
		printer = (self.printer_var.get() or "").strip()
		if not printer:
			messagebox.showerror(tr("settings_title"), tr("settings_error_printer"), parent=self)
			return
		try:
			interval = int((self.refresh_entry.get() or "").strip())
		except Exception:
			messagebox.showerror(tr("settings_title"), tr("settings_error_interval_number"), parent=self)
			return
		if interval < 2:
			messagebox.showerror(tr("settings_title"), tr("settings_error_interval_min"), parent=self)
			return

		self._value = AppSettings(
			printing_enabled=self.settings.printing_enabled,
			auto_refresh_enabled=self.settings.auto_refresh_enabled,
			ecard_enabled=self.settings.ecard_enabled,
			refresh_interval_sec=interval,
			printer_name=printer,
			fullscreen=self.settings.fullscreen,
			theme=self.settings.theme,
			appearance_mode=self.settings.appearance_mode,
			language=self.settings.language,
		)
		self.destroy()

	def _on_cancel(self) -> None:
		self._value = None
		self.destroy()

	def get_value(self) -> AppSettings | None:
		if self._value is None:
			return None
		return self._value


if __name__ == "__main__":
	app = App()
	app.mainloop()
