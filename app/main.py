"""MorrowFriends launcher UI."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from . import __version__
from .atmosphere import make_atmosphere, make_gear_icon
from .chat_inject import send_chat_command
from .config import profile_banner, write_ptt_state
from .crash_watch import classify_process_exit
from .coop import coop_summary
from .detect import detect_morrowind, save_remembered_path, validate_install
from .engine import (
    install_vc_runtime,
    live_roster,
    live_voice_snapshot,
    repair_tes3mp,
    start_client,
    tes3mp_ready,
    vc_runtime_ready,
)
from .deeplink import consume_startup_invite, register_protocol
from .invite import Invite
from .overlay import NearbyStrip
from .packs import VANILLA
from .paths import TES3MP_VERSION, tes3mp_dir
from .voice_chain import diagnose as diagnose_voice_chain
from .play import (
    PlayError,
    diagnose_failed_join,
    preflight_friend_invite,
    resolve_friend_invite,
)
from .recovery import RECOVERY_ACTION_LABELS
from .preferences import (
    load_first_run_complete,
    load_host_player_name,
    load_known_player_names,
    load_last_player_name,
    load_ptt_binding,
    load_voice_enabled,
    save_first_run_complete,
    save_friend_share_url,
    save_last_invite_token,
    save_last_player_name,
    save_ptt_binding,
    save_voice_enabled,
)
from .ptt_binding import binding_from_tk_key, binding_from_tk_mouse
from .ptt_bridge import LocalPttBridge, binding_virtual_key, load_allowed_voice_origins
from .tailscale import TailscaleCapability
from .theme import COLORS, ui_font
from .voice import distance_between, proximity_mix
from .voice_auto import (
    fetch_party_names,
    local_login_name,
    voice_join_url,
)
from .voice_client import friend_voice_url, load_voice_client_config, open_voice_client
from .voice_embed import VoiceEmbedder

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _hex_rgb(value: str) -> tuple[int, int, int]:
    """#rrggbb -> (r, g, b). Theme colours are hex; PIL wants a tuple."""
    h = value.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _asset_icon() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[1] / "packaging" / "morrowfriends.png",
        Path(__file__).resolve().parents[1] / "packaging" / "morrowfriends.ico",
        Path(getattr(sys, "_MEIPASS", "")) / "morrowfriends.png",
    ]
    for p in candidates:
        if p and p.is_file():
            return p
    return None


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"MorrowFriends  ·  v{__version__}")
        # 980x820 was smaller than the content, and no column scrolls, so the
        # voice controls and the Game files panel sat below the fold and simply
        # could not be reached without dragging the window bigger in repeated
        # testing. Size to what the layout actually needs, clamped to the
        # visible desktop so it still fits a small screen.
        # Sized to the tool, not to the screen. This is a one-action launcher:
        # once the host cockpit was removed the whole product is Play + name +
        # voice, roughly 600px tall. minsize(1000, 820) was left over from the
        # cockpit era and was FORCING ~250px of unowned space below the panel
        # no matter how tight the content got.
        # Lowered again on 2026-08-20 when hosting, the mode toggle and the
        # Game files drawer were removed: the layout now REQUESTS 444px, so a
        # 560 floor was padding ~120px of unowned backdrop under the panel for
        # the same reason the 820 floor did before it. Measured, not guessed.
        # Measured 2026-08-20: the layout REQUESTS 470x444, but the floors
        # were 860 wide — so ~418px of the window, nearly half of it, was empty
        # panel to the right of every control. friend_play itself is 293 wide.
        # Sized to the content now; the backdrop gets the desktop, not the panel.
        self.geometry("470x420")
        self.minsize(496, 410)
        self.configure(fg_color=COLORS["bg"])
        self.after(120, self._fit_window_to_content)

        self.install = None
        self.server_proc: subprocess.Popen | None = None
        self.client_proc: subprocess.Popen | None = None
        self._client_started_at = 0.0
        self._server_healed = False
        self._stopping_server = False
        self._active_invite: Invite | None = None
        self._busy = False
        self._join_probe_after: str | None = None
        self._join_probe_generation = 0
        self._join_parsed_invite: Invite | None = None
        self._join_capability = TailscaleCapability(False, False, False, True)
        # One public vanilla server. A pack picker was leftover from local
        # hosting; picking Tamriel Rebuilt would fail TES3MP's data-file check.
        self._photo = None
        self._brand_image = None
        self._hero_image = None
        self._atmosphere_image = None
        self._atmosphere_photo = None
        self._status_pulse_after: str | None = None
        self._voice_snapshot = None
        self._preferred_self_name = load_host_player_name()
        # Positions reach the relay from the game server's own uplink, so the
        # launcher's only voice job is this loopback push-to-talk companion:
        # browsers stop seeing key events the moment Morrowind takes focus.
        voice_origins = load_allowed_voice_origins()
        voice_origins.update(load_voice_client_config().allowed_origins)
        self._ptt_bridge = LocalPttBridge(voice_origins)
        self._ptt_bridge.start()
        self._apply_ptt_binding(load_ptt_binding())
        self._ptt_capturing = False
        # None (not False) so the first real reading always publishes, even if
        # the host happens to start with the key held down.
        self._last_published_ptt: bool | None = None
        # Filled by a worker thread; read by NearbyStrip's Tk callbacks so a
        # slow relay can never block the event loop.
        self._voice_names_cache: list[str] = []
        self.after(1500, self._refresh_voice_names_cache)
        # Latches so a persistent PTT publish failure is logged once, not 7x/s.
        self._ptt_publish_failed = False
        self.after(600, self._publish_ptt_state)
        self._startup_invite = consume_startup_invite()
        # Voice renders in THIS window now (see app/voice_embed.py). The view is
        # built on first use, and stays alive while hidden so stepping back to
        # Play does not drop the call.
        self._voice_embed = VoiceEmbedder()
        # Sticky: one CLR/pythonnet fault is enough. Retrying it on every
        # Open voice click is how this machine hung MorrowFriends.exe tonight.
        self._voice_embed_failed = ""
        self._voice_view: ctk.CTkFrame | None = None
        self._voice_host: tk.Frame | None = None
        self._play_geometry = ""
        self._play_panel: ctk.CTkFrame | None = None
        self._settings_view: ctk.CTkFrame | None = None
        self._overlay: NearbyStrip | None = None
        self._play_recovery_action = ""
        self._recovery_needed = False
        self._play_started_wall = 0.0
        self._applied_login_name = ""

        self._apply_window_icon()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._auto_detect)
        self.bind("<Configure>", self._on_shell_configure)
        register_protocol()

    def _apply_window_icon(self) -> None:
        icon = _asset_icon()
        if not icon:
            return
        try:
            if icon.suffix.lower() == ".ico":
                self.iconbitmap(default=str(icon))
            img = Image.open(icon).convert("RGBA")
            img = img.resize((64, 64), Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._photo)
        except (OSError, tk.TclError, ValueError):
            # A missing or unreadable icon file only costs us the taskbar
            # image. Narrowed from a blanket except so a real error in this
            # block is not silently swallowed with it.
            pass

    def _build(self) -> None:
        self._shell = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        self._shell.pack(fill="both", expand=True)

        self._atmosphere_label = ctk.CTkLabel(self._shell, text="", fg_color=COLORS["bg"])
        self._atmosphere_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._apply_atmosphere(980, 820)

        # Inset panel so the ash/ember field reads as a living frame. CTk
        # "transparent" inherits the parent solid color and cannot composite
        # through to a sibling backdrop label.
        content = ctk.CTkFrame(
            self._shell,
            # surface, NOT surface_low: measured against the theme, bg->surface
            # is 4.9 HSL-L points while bg->surface_low is 0.8 — the latter is
            # invisible on a near-black base, so the panel had no edge and the
            # region below it read as void rather than as backdrop.
            fg_color=COLORS["surface"],
            border_color=COLORS["line"],
            border_width=1,
            corner_radius=0,
        )
        # pack(), NOT place(relheight=0.936). place() with a relative height
        # scales this frame to a FRACTION OF THE WINDOW, which decouples the
        # window's required height from what is actually inside it: winfo_
        # reqheight() on the toplevel never grows with the content, nothing
        # scrolls, and any overflow is silently clipped. That is why the Game
        # files panel sat cut off mid-row until the window was dragged taller
        # in repeated testing. Packing makes the real content
        # height propagate so _fit_window_to_content can size to it.
        # fill="x", NOT fill="both"+expand=True. Expanding handed the panel
        # every spare pixel of window height, so ~450px of unowned dark sat
        # below the last element. The panel now ends just under its content and
        # the space beneath it belongs to the atmosphere backdrop.
        content.pack(fill="x", padx=22, pady=(18, 0))
        self._play_panel = content
        # Ember lip so the plaque reads as a lit tablet on the ash field,
        # not a floating grey box. tk.Frame: CTkFrame height=1 paints nothing.
        tk.Frame(
            content, bg=COLORS["ember"], height=2, bd=0, highlightthickness=0
        ).pack(fill="x")

        hero = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        hero.pack(fill="x", padx=22, pady=(14, 0))

        mark_row = ctk.CTkFrame(hero, fg_color="transparent", corner_radius=0)
        mark_row.pack(fill="x")

        icon = _asset_icon()
        if icon:
            try:
                self._hero_image = ctk.CTkImage(
                    light_image=Image.open(icon),
                    dark_image=Image.open(icon),
                    size=(36, 36),
                )
                ctk.CTkLabel(mark_row, text="", image=self._hero_image).pack(
                    side="left", padx=(0, 10)
                )
            except (OSError, tk.TclError, ValueError):
                # Decorative only — the header reads fine without the mark.
                pass

        ctk.CTkLabel(
            mark_row,
            text="MorrowFriends",
            font=ui_font("brand"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(side="left")

        # The gear replaces the old "Something's wrong" drawer. An icon earns
        # its place here because it IS the control — a settings gear needs no
        # label, and the alternative was a full-width text button that made the
        # Play screen look like it had two competing actions.
        gear = make_gear_icon(16, _hex_rgb(COLORS["muted"]))
        self._gear_image = ctk.CTkImage(light_image=gear, dark_image=gear, size=(16, 16))
        header_right = ctk.CTkFrame(mark_row, fg_color="transparent", corner_radius=0)
        header_right.pack(side="right")
        ctk.CTkLabel(
            header_right,
            text=f"v{__version__}",
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            anchor="e",
        ).pack(side="left", padx=(0, 8))
        self.settings_btn = ctk.CTkButton(
            header_right,
            text="",
            image=self._gear_image,
            width=28,
            height=28,
            corner_radius=0,
            fg_color="transparent",
            hover_color=COLORS["button_hover"],
            command=self._show_settings,
        )
        self.settings_btn.pack(side="left")
        self._back_btn = self._secondary_button(
            header_right, "Back", self._hide_settings_view
        )

        self.status_var = tk.StringVar(value="Looking for Morrowind…")
        self.status_label = ctk.CTkLabel(
            hero,
            textvariable=self.status_var,
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.status_label.pack(anchor="w", pady=(8, 0))

        self.friend_play = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        self._build_friend_play(self.friend_play)
        # Packed here, unconditionally. This used to be done by _apply_app_mode,
        # which existed only to swap between friend and host views — deleting
        # that method without moving the pack left the whole Play screen built
        # but never mapped, and the window rendered as a header and empty space.
        self.friend_play.pack(fill="x", padx=22, pady=(12, 16))

        # Hosting is gone entirely (2026-08-20). The party runs on a dedicated
        # server, admin lives in the web panel, and the desktop cockpit had been
        # a stale empty frame behind an "I'm hosting" toggle since 08-18. The
        # mode toggle, the host cockpit and the inline "Something's wrong"
        # drawer all went with it — path, pack and the repair tools now live
        # behind the gear, so the Play screen holds exactly one action.
        self.path_var = tk.StringVar(value="Searching…")

        self.progress_bar = ctk.CTkProgressBar(
            content,
            height=3,
            corner_radius=0,
            fg_color=COLORS["field"],
            progress_color=COLORS["ember"],
        )
        self.progress_bar.set(0)

        self.log(f"Ready · {profile_banner('vanilla')}")
        self.log(coop_summary())

    def _build_setup_drawer(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Game files",
            font=ui_font("label", size=12),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(fill="x")
        path_box = ctk.CTkFrame(
            parent,
            fg_color=COLORS["field"],
            border_color=COLORS["field_border"],
            border_width=1,
            corner_radius=0,
        )
        path_box.pack(fill="x", pady=(8, 0))
        self.path_label = ctk.CTkLabel(
            path_box,
            textvariable=self.path_var,
            font=ui_font("mono", size=11),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
        )
        self.path_label.pack(fill="x", padx=12, pady=9)

        def _wrap_path(event) -> None:
            inner = max(int(event.width) - 24, 80)
            if int(self.path_label.cget("wraplength") or 0) != inner:
                self.path_label.configure(wraplength=inner)

        path_box.bind("<Configure>", _wrap_path)
        btn_row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        btn_row.pack(fill="x", pady=(8, 0))
        self._secondary_button(
            btn_row, "Change", self._browse, height=32
        ).pack(side="left")
        self._secondary_button(
            btn_row, "Rescan", self._auto_detect, height=32
        ).pack(side="left", padx=(8, 0))

    def _build_recovery_tools(self, parent: ctk.CTkFrame) -> None:
        tk.Frame(
            parent, bg=COLORS["line"], height=1, bd=0, highlightthickness=0
        ).pack(fill="x", pady=(16, 12))
        ctk.CTkLabel(
            parent,
            text="If something is stuck",
            font=ui_font("label", size=13, weight="bold"),
            text_color=COLORS["secondary"],
            anchor="w",
        ).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            parent,
            text="Play does all of this on its own. Reach for these only if it fails.",
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(0, 8))

        # The invite-link field was removed on 2026-08-18: the party is a
        # public server, so there is no token to paste.

        # The /voice code field was removed on 2026-08-21. The game server keeps
        # an unused claim minted for every logged-in character and the voice page
        # redeems it by name, so there was never a code left for anyone to type.

        action_row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        action_row.pack(fill="x")
        for text, command in (
            # Tailscale buttons removed: nothing to install or accept for a
            # public server.
            ("Install C++", self._install_vc_runtime),
            ("Repair TES3MP", self._repair_engine),
            ("Voice position", self._show_voice_debug),
        ):
            self._secondary_button(action_row, text, command).pack(
                side="left", padx=(0, 8)
            )

        self.recovery_status_var = tk.StringVar(value="")
        self.recovery_status_label = ctk.CTkLabel(
            parent,
            textvariable=self.recovery_status_var,
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            wraplength=404,
            justify="left",
            anchor="w",
        )

    def _build_settings_view(self) -> ctk.CTkFrame:
        """Settings body inside the Play plaque. Built once, reused after that."""
        if self._settings_view is not None and self._settings_view.winfo_exists():
            return self._settings_view

        # Same plaque, same ash field. A second Toplevel is what sent Settings
        # behind Play on Windows. A second plaque is what
        # made this look like a different page.
        view = ctk.CTkFrame(
            self._play_panel, fg_color="transparent", corner_radius=0
        )

        ctk.CTkLabel(
            view,
            text="Voice",
            font=ui_font("label", size=12),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(fill="x")
        voice_row = ctk.CTkFrame(view, fg_color="transparent", corner_radius=0)
        voice_row.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(
            voice_row,
            text="Join voice when I play",
            font=ui_font("tiny"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(side="left")
        voice_var = ctk.BooleanVar(value=load_voice_enabled())

        def on_voice_toggle() -> None:
            enabled = bool(voice_var.get())
            save_voice_enabled(enabled)
            self._set_voice_status(
                "Voice attaches when you play." if enabled else "Voice is off.",
                "ok" if enabled else "",
            )

        ctk.CTkSwitch(
            voice_row,
            text="",
            width=42,
            variable=voice_var,
            command=on_voice_toggle,
            fg_color=COLORS["line"],
            progress_color=COLORS["ember"],
            button_color=COLORS["primary"],
            button_hover_color=COLORS["primary_hover"],
        ).pack(side="right")

        ptt = load_ptt_binding()
        ptt_row = ctk.CTkFrame(view, fg_color="transparent", corner_radius=0)
        ptt_row.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(
            ptt_row,
            text="Push-to-talk",
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
        ).pack(side="left")
        self._ptt_label_var = tk.StringVar(value=str(ptt["label"]))
        ctk.CTkLabel(
            ptt_row,
            textvariable=self._ptt_label_var,
            font=ui_font("label", size=13),
            text_color=COLORS["text"],
        ).pack(side="left", padx=(10, 0))
        self._ptt_status_var = tk.StringVar(value="Works while Morrowind has focus.")
        self._ptt_btn = self._secondary_button(
            ptt_row,
            "Change",
            lambda: None,
            width=self._chip_width("Press a key"),
            height=28,
        )
        self._ptt_btn.configure(
            command=lambda: self._start_ptt_capture(
                self._ptt_label_var, self._ptt_status_var, self._ptt_btn
            )
        )
        self._ptt_btn.pack(side="right")
        ctk.CTkLabel(
            view,
            textvariable=self._ptt_status_var,
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            wraplength=404,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        tk.Frame(
            view, bg=COLORS["line"], height=1, bd=0, highlightthickness=0
        ).pack(fill="x", pady=(14, 12))
        self._build_setup_drawer(view)

        self.recovery_tools = ctk.CTkFrame(view, fg_color="transparent", corner_radius=0)
        self._build_recovery_tools(self.recovery_tools)
        self.recovery_tools.pack(fill="x")

        self._settings_view = view
        return view

    def _show_settings(self) -> None:
        """Everything that is not Play, behind the gear.

        Same window, same plaque. A CTkToplevel was sent behind the launcher
        on Windows. An inline drawer is also wrong: it resized Play under the
        cursor. Swap the body. Back sits where the gear was.
        """
        self._build_settings_view()
        if self._settings_view.winfo_ismapped():
            return
        if self._voice_view is not None and self._voice_view.winfo_ismapped():
            self._voice_view.pack_forget()
            self._shell.pack(fill="both", expand=True)
        if self.friend_play.winfo_ismapped():
            self._play_geometry = self.geometry()
            self.friend_play.pack_forget()
        self.settings_btn.pack_forget()
        self._back_btn.pack(side="left")
        self._settings_view.pack(fill="x", padx=22, pady=(12, 16))
        self.update_idletasks()
        width = max(self.winfo_width(), 496)
        max_h = max(self.winfo_screenheight() - 140, 780)
        height = min(max(self.winfo_reqheight() + 36, 410), max_h)
        self.geometry(f"{int(width)}x{int(height)}")

    def _hide_settings_view(self) -> None:
        """Return to Play. Does not expand or collapse a drawer."""
        if self._ptt_capturing and hasattr(self, "_ptt_btn"):
            self._finish_ptt_capture(
                None, self._ptt_label_var, self._ptt_status_var, self._ptt_btn
            )
        if self._settings_view is not None and self._settings_view.winfo_exists():
            self._settings_view.pack_forget()
        if self._back_btn.winfo_ismapped():
            self._back_btn.pack_forget()
        if not self.settings_btn.winfo_ismapped():
            self.settings_btn.pack(side="left")
        if not self.friend_play.winfo_ismapped():
            self.friend_play.pack(fill="x", padx=22, pady=(12, 16))
        self.minsize(496, 410)
        if self._play_geometry:
            self.geometry(self._play_geometry)

    def _apply_atmosphere(self, width: int, height: int) -> None:
        try:
            raw = make_atmosphere(max(width, 800), max(height, 600))
            self._atmosphere_image = ctk.CTkImage(
                light_image=raw, dark_image=raw, size=(max(width, 1), max(height, 1))
            )
            self._atmosphere_label.configure(image=self._atmosphere_image)
        except Exception:
            self._atmosphere_label.configure(image=None, fg_color=COLORS["bg"])

    def _on_shell_configure(self, event) -> None:
        if event.widget is not self:
            return
        if event.width < 200 or event.height < 200:
            return
        # Debounce regenerating the stretched backdrop.
        if getattr(self, "_atmosphere_resize_after", None):
            try:
                self.after_cancel(self._atmosphere_resize_after)
            except tk.TclError:
                # The timer already fired; nothing to cancel.
                pass
        self._atmosphere_resize_after = self.after(
            120, lambda: self._apply_atmosphere(event.width, event.height)
        )

    def _set_status(self, message: str, kind: str = "muted") -> None:
        self.status_var.set(message)
        color = {
            "ok": COLORS["ok"],
            "warn": COLORS["warn"],
            # Red is reserved for fills and bars; as text it fails AA.
            "error": COLORS["warn"],
            "live": COLORS["ember"],
            "muted": COLORS["muted"],
        }.get(kind, COLORS["muted"])
        if hasattr(self, "status_label"):
            self.status_label.configure(text_color=color)
            self._pulse_status()

    def _pulse_status(self) -> None:
        if not hasattr(self, "status_label"):
            return
        if self._status_pulse_after:
            try:
                self.after_cancel(self._status_pulse_after)
            except tk.TclError:
                # The pulse already fired; nothing to cancel.
                pass
        original = self.status_label.cget("text_color")
        self.status_label.configure(text_color=COLORS["primary"])

        def restore() -> None:
            try:
                self.status_label.configure(text_color=original)
            except tk.TclError:
                # The window closed before the pulse restored; harmless.
                pass

        self._status_pulse_after = self.after(160, restore)

    def _field(self, parent, width=300) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            width=width,
            height=36,
            corner_radius=0,
            fg_color=COLORS["field"],
            border_color=COLORS["field_border"],
            border_width=1,
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["muted"],
            font=ui_font("body", size=13),
        )

    def _chip_width(self, text: str, *, size: int = 12) -> int:
        """Pixel width of a secondary button: the label plus tight side pads."""
        font = ui_font("label", size=size)
        try:
            measured = int(font.measure(text))
        except (AttributeError, tk.TclError, TypeError):
            measured = tkfont.Font(
                family=str(font.cget("family")),
                size=int(font.cget("size")),
                weight=str(font.cget("weight")),
            ).measure(text)
        return measured + 20

    def _secondary_button(
        self,
        parent,
        text: str,
        command,
        *,
        width: int | None = None,
        height: int = 28,
        font_size: int = 12,
    ) -> ctk.CTkButton:
        # Default 118px left "Change" and "Install C++" sitting in empty
        # rectangles. Size to the words unless the caller needs a stretch
        # (Play's Fix this) or a stable width for a label that changes.
        if width is None:
            width = self._chip_width(text, size=font_size)
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=height,
            corner_radius=0,
            fg_color=COLORS["button"],
            hover_color=COLORS["button_hover"],
            text_color=COLORS["secondary"],
            font=ui_font("label", size=font_size),
            command=command,
        )

    def _build_friend_play(self, parent: ctk.CTkFrame) -> None:
        # Name first, then Play. The old stack put the button above the name
        # field, so the one thing you have to type sat under the one action.
        known = load_known_player_names()
        self.friend_name_var = tk.StringVar(
            value=load_last_player_name() or (known[0] if known else "")
        )
        you_row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        you_row.pack(fill="x")
        ctk.CTkLabel(
            you_row,
            text="You are",
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
        ).pack(side="left")
        # Only worth a picker when there is something to pick BETWEEN. With one
        # saved name the dropdown just repeated the text field beside it, so the
        # same name appeared three times on one row — field, menu, and the
        # menu's open list.
        if len(known) > 1:
            self.friend_name_menu = ctk.CTkOptionMenu(
                you_row,
                values=known,
                command=lambda value: self.friend_name_var.set(value),
                width=132,
                height=24,
                corner_radius=0,
                fg_color=COLORS["field"],
                button_color=COLORS["accent_soft"],
                button_hover_color=COLORS["line_strong"],
                dropdown_fg_color=COLORS["surface"],
                dropdown_hover_color=COLORS["button_hover"],
                text_color=COLORS["text"],
                font=ui_font("tiny"),
            )
            self.friend_name_menu.set(self.friend_name_var.get() or known[0])
            self.friend_name_menu.pack(side="right")

        self.friend_name_entry = self._field(parent, width=10)
        self.friend_name_entry.configure(
            textvariable=self.friend_name_var,
            placeholder_text="Character name",
        )
        self.friend_name_entry.pack(fill="x", pady=(6, 0))
        # Enter launches, so name-then-Enter is a complete path without the
        # mouse ever moving to the Play button.
        self.friend_name_entry.bind("<Return>", lambda _e: self._play_now())

        self.play_now_btn = ctk.CTkButton(
            parent,
            text="Play",
            width=10,
            height=52,
            corner_radius=0,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            text_color=COLORS["surface_low"],
            font=ui_font("button", size=20),
            command=self._play_now,
        )
        self.play_now_btn.pack(fill="x", pady=(12, 0))

        # Empty by default. It keeps reserved height so an async status
        # message has somewhere to land without resizing the window.
        self.play_status_var = tk.StringVar(value="")
        ctk.CTkLabel(
            parent,
            textvariable=self.play_status_var,
            font=ui_font("tiny"),
            text_color=COLORS["secondary"],
            # Must stay under the panel's inner width or a long message demands
            # 560px and drags the whole window back out to its old size.
            wraplength=404,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

        self.play_recovery_btn = self._secondary_button(
            parent, "Fix this", self._run_play_recovery, width=10, height=34
        )

        self.first_run_hint = ctk.CTkLabel(
            parent,
            # Tailscale is NOT needed any more — the party runs on a public
            # server, so there is no account to make and no share to accept.
            # Asking for one sent friends off to install software that does
            # nothing for them.
            text="First time: Morrowind GOTY. Type the name you will create, or leave You are blank.",
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            wraplength=404,
            justify="left",
            anchor="w",
        )
        if not load_first_run_complete():
            self.first_run_hint.pack(fill="x", pady=(8, 0))

        # Voice status now lives on the Play screen. These vars used to be
        # created inside the host cockpit, which was deleted on 2026-08-18 —
        # every voice status update wrote to a widget that no longer existed.
        self._play_footer = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        self._play_footer.pack(fill="x", pady=(14, 0))
        tk.Frame(
            self._play_footer,
            bg=COLORS["line"],
            height=1,
            bd=0,
            highlightthickness=0,
        ).pack(fill="x", pady=(0, 10))
        voice_row = ctk.CTkFrame(self._play_footer, fg_color="transparent", corner_radius=0)
        voice_row.pack(fill="x")
        self.voice_status_var = tk.StringVar(
            value="Voice attaches when you play."
            if load_voice_enabled()
            else "Voice is off."
        )
        self.voice_status_label = ctk.CTkLabel(
            voice_row,
            textvariable=self.voice_status_var,
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.voice_status_label.pack(side="left", fill="x", expand=True)
        self.open_voice_main_btn = self._secondary_button(
            voice_row, "Open voice", self._open_voice_client
        )
        self.open_voice_main_btn.pack(side="right")
        # Kept so _update_voice_position_status has somewhere to write; the
        # detail is only surfaced in the Voice debug window now.
        self.voice_position_status_var = tk.StringVar(value="")

    def _note_recovery(self, message: str) -> None:
        if hasattr(self, "recovery_status_var"):
            self.recovery_status_var.set(message)
            if hasattr(self, "recovery_status_label"):
                if message and not self.recovery_status_label.winfo_ismapped():
                    self.recovery_status_label.pack(anchor="w", pady=(8, 0))
                elif not message and self.recovery_status_label.winfo_ismapped():
                    self.recovery_status_label.pack_forget()
        if hasattr(self, "play_status_var"):
            self.play_status_var.set(message)

    def _set_play_status(self, message: str, action: str = "") -> None:
        self.play_status_var.set(message)
        self._play_recovery_action = action
        if action:
            self._recovery_needed = True
            self.play_recovery_btn.configure(
                text=RECOVERY_ACTION_LABELS.get(action, "Fix this")
            )
            if not self.play_recovery_btn.winfo_ismapped():
                self.play_recovery_btn.pack(
                    fill="x", pady=(8, 0), before=self._play_footer
                )
        elif self.play_recovery_btn.winfo_ismapped():
            self.play_recovery_btn.pack_forget()


    def _open_recovery_voice(self) -> None:
        """Reopen the voice page for this character. No code to type any more."""
        self._open_voice_client()

    def _run_play_recovery(self) -> None:
        action = self._play_recovery_action
        if action == "browse":
            self._browse()
        elif action == "vc":
            self._install_vc_runtime()
        elif action == "invite":
            self._show_settings()
        elif action == "voice":
            self._open_recovery_voice()
        elif action == "repair":
            self._repair_engine()

    def _play_now(self) -> None:
        # Hosting from this PC is gone; Play always joins the party server.
        if not self._require_install():
            self._set_play_status("Morrowind GOTY was not found.", "browse")
            return
        if not self._require_vc_runtime():
            self._set_play_status("The Microsoft C++ runtime is missing.", "vc")
            return

        def work() -> None:
            def cb(msg: str) -> None:
                self.after(0, lambda m=msg: self._set_play_status(m))

            try:
                invite = resolve_friend_invite(startup=self._startup_invite)
                preflight_friend_invite(invite)
            except PlayError as exc:
                self.after(0, lambda e=exc: self._set_play_status(str(e), e.action))
                return
            # Invite used to carry a join password. The server is open now.
            self.client_proc = start_client(
                self.install, invite, pack=VANILLA.id, cb=cb
            )
            self._client_started_at = time.monotonic()
            save_last_invite_token(invite.to_token())
            if invite.share_url:
                save_friend_share_url(invite.share_url)
            self._startup_invite = invite
            self.after(0, self._finish_play_session)

        self._set_play_status("Starting the party…")
        self._run_bg(work)

    def _finish_play_session(self) -> None:
        save_first_run_complete(True)
        self._recovery_needed = False
        if hasattr(self, "first_run_hint") and self.first_run_hint.winfo_ismapped():
            self.first_run_hint.pack_forget()
        self._play_started_wall = time.time()
        self._applied_login_name = ""
        player = self._chosen_player_name()
        want_voice = load_voice_enabled()
        if player:
            save_last_player_name(player)
            self._applied_login_name = player
        if not want_voice:
            self._set_play_status("Game is launching. Voice is off.")
            self._set_voice_status("Voice is off.")
        elif player:
            self._set_play_status("Game is launching. Voice attaches when your character loads.")
            # Same window as Open voice. The Edge fallback is only if embed
            # cannot start.
            self._open_voice_client()
        else:
            # Do not open voice with an empty name. The page would snapshot
            # /health and might never see this login, or guess if two people
            # appear. This machine's TES3MP log knows who we are.
            self._set_play_status("Game is launching. Voice attaches after you log in.")
            self._set_voice_status("Waiting for your TES3MP login…")
        self._set_status("Party starting", "live")
        threading.Thread(target=self._watch_local_login, daemon=True).start()
        self._show_nearby_strip()
        self.after(1500, self._watch_client_proc)

    def _watch_local_login(self) -> None:
        """Fill You are from THIS client's log once TES3MP prints Welcome."""
        started = time.monotonic()
        since = self._play_started_wall
        while time.monotonic() - started < 30 * 60:
            name = local_login_name(since=since)
            if name:
                self.after(0, lambda found=name: self._apply_local_login_name(found))
                return
            if self.client_proc is None and time.monotonic() - started > 20:
                return
            time.sleep(2)

    def _apply_local_login_name(self, name: str) -> None:
        """Identity from this PC's TES3MP client. Never from the party list."""
        name = name.strip()
        if not name:
            return
        already = self._applied_login_name.strip()
        if hasattr(self, "friend_name_var"):
            self.friend_name_var.set(name)
        save_last_player_name(name)
        if already.casefold() == name.casefold():
            self._applied_login_name = name
            return
        self._applied_login_name = name
        if not load_voice_enabled():
            self._set_play_status(f"Logged in as {name}.")
            self._set_voice_status("Voice is off.")
            return
        self._set_play_status(f"Logged in as {name}. Voice is attaching.")
        self._set_voice_status(f"Attaching as {name}.", "ok")
        self._open_voice_client()

    def _show_nearby_strip(self) -> None:
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.deiconify()
            return

        def names() -> list[str]:
            roster = [str(row.get("name", "")) for row in live_roster() if row.get("name")]
            if roster:
                return roster
            # Cache again — same six-second-freeze reason as voice_names().
            return list(self._voice_names_cache)

        def goto(name: str) -> None:
            # send_chat_command sleeps ~300ms on SendInput. NearbyStrip calls
            # this from the Tk event loop, and that sleep is what painted
            # "MorrowFriends nearby (Not Responding)".
            def worker() -> None:
                result = send_chat_command(f"/goto {name}")

                def apply() -> None:
                    if result.ok:
                        if self._overlay is not None and self._overlay.winfo_exists():
                            self._overlay.ptt_var.set(f"Sent /goto {name}")
                        return
                    self.clipboard_clear()
                    self.clipboard_append(f"/goto {name}")
                    if self._overlay is not None and self._overlay.winfo_exists():
                        self._overlay.ptt_var.set(f"Copied /goto {name} — press Y in game")

                self.after(0, apply)

            threading.Thread(target=worker, daemon=True).start()

        def voice_names() -> list[str]:
            # Return the CACHE. NearbyStrip calls this from the Tk event loop,
            # and fetch_party_names() is a urlopen with a 6s timeout — calling
            # it directly freezes the overlay for six seconds every time the
            # relay is slow or unreachable.
            return list(self._voice_names_cache)

        self._overlay = NearbyStrip(
            self,
            names_source=names,
            goto_callback=goto,
            ptt_source=self._ptt_bridge.talking,
            voice_names_source=voice_names,
        )

    def log(self, msg: str) -> None:
        print(msg)
        m = re.search(r"Downloading TES3MP.*?(\d+)%", msg)
        if m:
            self._show_progress(int(m.group(1)) / 100)
        elif msg.startswith(("TES3MP", "Server running", "ERROR")) or "ready" in msg:
            self._hide_progress()

    def _show_progress(self, fraction: float) -> None:
        self.progress_bar.pack(side="bottom", fill="x", padx=22, pady=(0, 10))
        self.progress_bar.set(fraction)

    def _hide_progress(self) -> None:
        self.progress_bar.pack_forget()



    def _publish_ptt_state(self) -> None:
        """Push the host's mic state to the server for the in-game indicator.

        Own loop at 150ms, NOT _poll_roster's 3s tick — push-to-talk feedback
        has to feel immediate. Only writes on a CHANGE so the file is not
        rewritten 7x a second while nobody is talking.
        """
        try:
            talking = bool(self._ptt_bridge.talking())
            name = self._chosen_player_name()
            if name and talking != self._last_published_ptt:
                write_ptt_state(tes3mp_dir(), name, talking)
                self._last_published_ptt = talking
        except Exception as exc:
            # Report ONCE rather than silently retrying seven times a second
            # forever. The loop keeps running (a transient file lock should
            # recover), but a persistent failure is now visible instead of
            # invisible.
            if not self._ptt_publish_failed:
                self._ptt_publish_failed = True
                self.log(f"In-game voice indicator unavailable: {exc}")
        self.after(150, self._publish_ptt_state)

    def _update_voice_position_status(self) -> None:
        snapshot = live_voice_snapshot()
        self._voice_snapshot = snapshot
        if snapshot.version < 1:
            self.voice_position_status_var.set("Voice positions: available after server restart")
        elif snapshot.is_stale():
            self.voice_position_status_var.set("Voice positions: stale (audio will mute)")
        else:
            self.voice_position_status_var.set(
                f"Voice positions: live · {len(snapshot.players)} players · #{snapshot.sequence}"
            )

    def _show_voice_debug(self) -> None:
        window = ctk.CTkToplevel(self)
        window.title("MorrowFriends voice position diagnostic")
        window.geometry("640x430")
        window.minsize(560, 360)
        window.configure(fg_color=COLORS["bg"])

        status_var = tk.StringVar(value="")
        ctk.CTkLabel(
            window,
            text="Proximity voice diagnostic",
            text_color=COLORS["text"],
            font=ui_font("heading", size=16, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 4))
        ctk.CTkLabel(
            window,
            textvariable=status_var,
            text_color=COLORS["muted"],
            font=ui_font("label", size=11),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 8))
        output = ctk.CTkTextbox(
            window,
            fg_color=COLORS["surface_low"],
            text_color=COLORS["text"],
            font=ui_font("mono", size=12),
            border_width=1,
            border_color=COLORS["field_border"],
            corner_radius=0,
        )
        output.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        def refresh() -> None:
            snapshot = live_voice_snapshot()
            listener_name = self._self_name()
            output.configure(state="normal")
            output.delete("1.0", "end")
            # Chain check FIRST. "Voice doesn't work" looked identical four
            # separate times on 2026-08-18 while the actual broken link was
            # different every time (server crashed / launcher closed / media
            # connection failed / wrong identity claimed). Name the link.
            try:
                config = load_voice_client_config()
                report = diagnose_voice_chain(
                    tes3mp_dir(),
                    friend_voice_url().split("?", 1)[0].rstrip("/"),
                    config.party_id,
                )
                output.insert("end", "Voice chain\n")
                for link in report.links:
                    mark = "OK  " if link.ok else "FAIL"
                    output.insert("end", f"  [{mark}] {link.name}: {link.detail}\n")
                output.insert("end", f"\n{report.summary()}\n\n")
            except Exception as exc:
                output.insert("end", f"Chain check failed: {exc}\n\n")
            if snapshot.version < 1:
                status_var.set("No versioned position feed yet.")
                output.insert("end", "Restart the server with the voice-enabled build first.\n")
            elif not listener_name:
                status_var.set("Type your in-game name under \"You are\" first.")
            else:
                age = max(0.0, time.monotonic() - snapshot.observed_at)
                stale = snapshot.is_stale()
                status_var.set(
                    f"Listener: {listener_name} · snapshot #{snapshot.sequence} · "
                    f"age {age:.2f}s · {'STALE / MUTED' if stale else 'LIVE'}"
                )
                listener = next(
                    (player for player in snapshot.players if player.name == listener_name),
                    None,
                )
                gains = proximity_mix(snapshot, listener_name)
                if listener is None:
                    output.insert("end", "The selected listener is not in the position feed.\n")
                else:
                    output.insert("end", "SPEAKER                 DISTANCE    GAIN   SPACE\n")
                    output.insert("end", "--------------------------------------------------------\n")
                    for speaker in snapshot.players:
                        if speaker.name == listener_name:
                            continue
                        distance = distance_between(listener, speaker)
                        distance_text = "blocked" if distance is None else f"{distance:7.0f}u"
                        space = (
                            "exterior"
                            if listener.exterior and speaker.exterior
                            else "same interior"
                            if distance is not None
                            else "different cell"
                        )
                        output.insert(
                            "end",
                            f"{speaker.name[:22]:22}  {distance_text:>9}  "
                            f"{gains.get(speaker.name, 0.0):5.2f}   {space}\n",
                        )
            output.configure(state="disabled")

        ctk.CTkButton(
            window,
            text="Refresh",
            width=90,
            height=32,
            corner_radius=0,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            text_color=COLORS["surface_low"],
            command=refresh,
        ).pack(anchor="e", padx=18, pady=(0, 14))
        refresh()

    def _apply_ptt_binding(self, binding: dict) -> None:
        value = (
            str(binding.get("code") or "Space")
            if binding.get("kind") == "keyboard"
            else str(binding.get("button", 0))
        )
        virtual_key = binding_virtual_key(str(binding.get("kind") or "keyboard"), value)
        if virtual_key is not None:
            self._ptt_bridge.remember_binding(virtual_key)

    def _start_ptt_capture(self, label_var, status_var, button) -> None:
        if self._ptt_capturing:
            self._finish_ptt_capture(None, label_var, status_var, button)
            return
        self._ptt_capturing = True
        button.configure(text="Press a key")
        status_var.set("Press one key or mouse button. Escape cancels.")

        def on_key(event) -> str:
            if not self._ptt_capturing:
                return "break"
            if event.keysym == "Escape":
                self._finish_ptt_capture(None, label_var, status_var, button)
                return "break"
            binding = binding_from_tk_key(event.keysym)
            if binding:
                self._finish_ptt_capture(binding, label_var, status_var, button)
            return "break"

        def on_mouse(event) -> str:
            if not self._ptt_capturing:
                return "break"
            binding = binding_from_tk_mouse(int(event.num))
            if binding:
                self._finish_ptt_capture(binding, label_var, status_var, button)
            return "break"

        # Let the click that opened capture finish before we listen for a mouse
        # button, or Change would bind itself as push-to-talk.
        def arm() -> None:
            if not self._ptt_capturing or not self.winfo_exists():
                return
            self.bind("<KeyPress>", on_key)
            self.bind("<ButtonPress>", on_mouse)
            self.focus_force()

        self.after(80, arm)

    def _finish_ptt_capture(self, binding, label_var, status_var, button) -> None:
        self._ptt_capturing = False
        if self.winfo_exists():
            self.unbind("<KeyPress>")
            self.unbind("<ButtonPress>")
        button.configure(text="Change")
        if binding is None:
            status_var.set(f"Kept {load_ptt_binding()['label']}.")
            return
        saved = save_ptt_binding(binding)
        self._apply_ptt_binding(saved)
        label_var.set(str(saved["label"]))
        status_var.set(f"{saved['label']} is push-to-talk.")

    def _set_voice_status(self, message: str, kind: str = "") -> None:
        colors = {"ok": COLORS["ok"], "warn": COLORS["warn"]}
        self.voice_status_var.set(message)
        self.voice_status_label.configure(text_color=colors.get(kind, COLORS["muted"]))

    def _refresh_voice_names_cache(self) -> None:
        """Poll the relay for who is in voice, off the Tk thread.

        fetch_party_names() is urlopen(timeout=6). Called inline from a Tk
        callback it freezes the whole UI for up to six seconds whenever the
        relay is slow — and NearbyStrip polls every few seconds.
        """

        def worker() -> None:
            try:
                names = fetch_party_names(
                    friend_voice_url().split("?", 1)[0].rstrip("/")
                )
            except Exception:
                names = []
            # Hand the result back on the Tk thread; never touch widgets here.
            self.after(0, lambda: setattr(self, "_voice_names_cache", names))

        threading.Thread(target=worker, daemon=True).start()
        self.after(5000, self._refresh_voice_names_cache)

    def _fit_window_to_content(self, attempt: int = 0) -> None:
        """Grow the window so nothing sits below the fold, clamped to the screen.

        No column in this layout scrolls, so content taller than the window is
        unreachable — the user has to drag the frame bigger to find it, which
        Repeated testing found the Game files panel cut off mid-row.

        Measured REPEATEDLY on purpose. A single early pass reads an
        incomplete layout: widgets built later in __init__, fonts resolved
        asynchronously, and drawers toggled after first paint all change the
        required height, and the first measurement silently under-reports it.
        """
        try:
            self.update_idletasks()
            # Floors match minsize(). They used to be 1000x820 — the cockpit-era
            # figures — which silently re-imposed the tall window even after
            # minsize was lowered, keeping the unowned band alive.
            need_w = max(self.winfo_reqwidth(), 496)
            need_h = max(self.winfo_reqheight(), 410)
            # Leave room for the taskbar and window chrome.
            max_w = max(self.winfo_screenwidth() - 80, 1000)
            max_h = max(self.winfo_screenheight() - 140, 780)
            width = min(need_w + 28, max_w)
            height = min(need_h + 36, max_h)
            # Grow AND shrink. Grow-only latched onto whatever the tallest
            # transient state was — the Game files drawer is expanded while the
            # path is still resolving and collapses a moment later, so the
            # window kept that taller size forever and the reclaimed space
            # became an unowned band. Later passes are allowed to pull it back
            # in; the first pass still only grows, so a slow-resolving layout is
            # never squeezed before it has finished measuring.
            if width > self.winfo_width() or height > self.winfo_height():
                self.geometry(f"{int(width)}x{int(height)}")
            elif attempt >= 2 and (
                self.winfo_height() - height > 40 or self.winfo_width() - width > 40
            ):
                self.geometry(f"{int(width)}x{int(height)}")
        except Exception:
            # Sizing is a convenience; never let it stop the app from opening.
            return
        if attempt < 4:
            self.after(450, lambda: self._fit_window_to_content(attempt + 1))

    def _build_voice_view(self) -> tk.Frame:
        """The in-window voice screen. Built once, reused after that."""
        if self._voice_view is not None and self._voice_view.winfo_exists():
            return self._voice_host

        view = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        tk.Frame(
            view, bg=COLORS["ember"], height=2, bd=0, highlightthickness=0
        ).pack(fill="x")
        header = ctk.CTkFrame(view, fg_color="transparent", corner_radius=0)
        header.pack(fill="x", padx=14, pady=(10, 8))
        ctk.CTkLabel(
            header,
            text="Proximity voice",
            font=ui_font("heading", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(side="left")
        self._secondary_button(
            header, "Back", self._hide_voice_view
        ).pack(side="right")

        # A plain tk.Frame: this is reparented to at the Win32 level, so it must
        # be a real HWND and not something customtkinter draws on a canvas.
        host = tk.Frame(view, bg=COLORS["bg"], bd=0, highlightthickness=0)
        host.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        host.pack_propagate(False)
        host.bind("<Configure>", lambda _event: self._voice_embed.fit())

        self._voice_view = view
        self._voice_host = host
        return host

    def _show_voice_view(self, url: str) -> bool:
        """Swap the window over to voice. False means the caller should fall back."""
        if self._settings_view is not None and self._settings_view.winfo_ismapped():
            self._hide_settings_view()
        host = self._build_voice_view()
        self._play_geometry = self.geometry()
        self._shell.pack_forget()
        self._voice_view.pack(fill="both", expand=True)
        # The Play screen is deliberately short; the voice page needs real
        # height, so the window grows only while voice is on screen.
        self.minsize(470, 600)
        self.geometry("500x780")
        self.update_idletasks()

        try:
            result = self._voice_embed.start(host, url)
        except Exception as exc:  # noqa: BLE001 — pythonnet can raise CLR errors
            self._voice_embed_failed = f"{type(exc).__name__}: {exc}"
            self._hide_voice_view()
            return False
        if not result.ok:
            self._voice_embed_failed = result.detail
            self._hide_voice_view()
            return False
        self._voice_embed.fit()
        return True

    def _hide_voice_view(self) -> None:
        """Return to Play. The call keeps running behind the scenes."""
        if self._voice_view is not None and self._voice_view.winfo_exists():
            self._voice_view.pack_forget()
        self._shell.pack(fill="both", expand=True)
        self.minsize(496, 410)
        if self._play_geometry:
            self.geometry(self._play_geometry)

    def _open_voice_client(self) -> None:
        # The server already writes a code -> player map for every connected
        # character, so nobody should ever read a code off the game screen and
        # retype it — Morrowind runs fullscreen and its chat is not selectable
        # text, so that was not just tedious, it was frequently impossible.
        # This used to call open_voice_client() with a bare page URL and ignore
        # that map entirely; only the auto-Play path ever used it.
        player = self._chosen_player_name()
        url = voice_join_url(player=player or "")

        # Voice belongs in this window. Only fall back to a second window when
        # embedding is genuinely unavailable — missing WebView2, or a previous
        # pythonnet fault on this machine (2026-08-21, Python.Runtime crash).
        if not self._voice_embed_failed and self._show_voice_view(url):
            detail = f"Voice open as {player}." if player else "Voice is open."
            self._set_voice_status(detail, "ok")
            return

        launch = open_voice_client(url=url)
        if launch.ok and player:
            launch = replace(launch, detail=f"Voice opened as {player}.")
        status = launch.detail if launch.ok else f"Voice open failed: {launch.detail}"
        self._set_voice_status(status, "ok" if launch.ok else "warn")
        if not launch.ok:
            messagebox.showwarning("Proximity voice", status)

    def _on_close(self) -> None:
        self._ptt_bridge.stop(timeout=1.0)
        # The WebView2 host runs its own message loop on a .NET thread; without
        # this it outlives the window it was drawn into.
        self._voice_embed.stop()
        self.destroy()


    def _self_name(self) -> str | None:
        """The player's character name, from the Play screen.

        Used to read self_name_menu in the host cockpit, which was deleted on
        2026-08-18. Friend mode's name field is the only source now.
        """
        if hasattr(self, "friend_name_var"):
            val = self.friend_name_var.get().strip()
            return val or None
        return load_host_player_name() or None

    def _chosen_player_name(self) -> str:
        if hasattr(self, "friend_name_var"):
            typed = self.friend_name_var.get().strip()
            if typed:
                return typed
        return (
            self._self_name()
            or load_last_player_name()
            or load_host_player_name()
            or ""
        )

    def _watch_client_proc(self) -> None:
        exit_state = classify_process_exit(
            self.client_proc,
            started_at=self._client_started_at,
            tes3mp_ok=tes3mp_ready() is not None,
            vc_ok=vc_runtime_ready(),
        )
        if exit_state is None:
            self.after(1500, self._watch_client_proc)
            return
        self.client_proc = None
        if exit_state.kind == "crash":
            # Diagnose AFTER a real failure, never before one. The old
            # preflight gate blocked people who could actually connect; this
            # runs only once an attempt has genuinely died.
            if exit_state.action == "repair" and self._startup_invite is not None:
                reason = diagnose_failed_join(self._startup_invite)
                if reason:
                    self._set_play_status(reason, "share")
                    return
            self._set_play_status(exit_state.message, exit_state.action)
            if exit_state.action == "repair" and tes3mp_ready() is None:
                self._repair_engine()
            return
        self._set_play_status(exit_state.message)



    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _require_install(self) -> bool:
        if self.install is None:
            return False
        return True

    def _auto_detect(self) -> None:
        self.path_var.set("Searching…")
        self._set_status("Looking for Morrowind…", "muted")
        result = detect_morrowind()
        if result.ok and result.install:
            self.install = result.install
            save_remembered_path(result.install.root)
            self.path_var.set(result.install.display)
            self._set_status(
                f"Ready · {result.install.source.title()} · GOTY found", "ok"
            )
            self.log(f"Detected Morrowind via {result.install.source}: {result.install.root}")
        else:
            self.install = result.install
            self.path_var.set(str(result.install.root) if result.install else "(not found)")
            self._set_status(result.message.split("\n")[0], "warn")
            self.log(result.message)

    def _browse(self) -> None:
        path = filedialog.askdirectory(title="Select Morrowind folder (or Data Files)")
        if not path:
            return
        result = validate_install(Path(path), source="manual")
        if result.ok and result.install:
            self.install = result.install
            save_remembered_path(result.install.root)
            self.path_var.set(result.install.display)
            self._set_status("Ready · Manual · GOTY found", "ok")
            self.log(f"Using manual path: {result.install.root}")
        else:
            self._set_status(result.message.split("\n")[0], "warn")
            messagebox.showerror("Invalid install", result.message)
            self.log(result.message)


    def _run_bg(self, work) -> None:
        if self._busy:
            self.log("Already working…")
            return

        self._set_busy(True)

        def runner() -> None:
            try:
                work()
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)
                self.after(0, lambda message=detail: messagebox.showerror("Error", message))
                self.after(0, lambda message=detail: self.log(f"ERROR: {message}"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=runner, daemon=True).start()




    def _vc_widget(self, name: str):
        """Return a cockpit widget, or None when the cockpit is not built."""
        return getattr(self, name, None)

    def _set_vc_status(self, message: str, tone: str = "muted") -> None:
        """Report VC-runtime state through whichever surface exists."""
        var = self._vc_widget("vc_runtime_status_var")
        if var is not None:
            var.set(message)
        label = self._vc_widget("vc_runtime_status_label")
        if label is not None:
            label.configure(text_color=COLORS[tone])

    def _refresh_vc_runtime_status(self) -> bool:
        ready = vc_runtime_ready()
        btn = self._vc_widget("install_vc_runtime_btn")
        bar = self._vc_widget("vc_runtime_progress")
        if ready:
            self._set_vc_status("Installed — TES3MP can start normally.", "ok")
            if btn is not None:
                btn.pack_forget()
            if bar is not None:
                bar.pack_forget()
        else:
            self._set_vc_status(
                "Missing — TES3MP may flash and close until this is installed.",
                "warn",
            )
            if btn is not None and not btn.winfo_manager():
                btn.pack(anchor="w")
        return ready

    def _require_vc_runtime(self) -> bool:
        # Friend mode is the only mode. Report through the Play status line and
        # let "Fix this" run the install — never a modal the player did not ask
        # for while they are trying to press Play.
        return self._refresh_vc_runtime_status()

    def _install_vc_runtime(self) -> None:
        if self._refresh_vc_runtime_status():
            messagebox.showinfo(
                "C++ component ready",
                "The required Microsoft C++ component is already installed.",
            )
            return
        if self._busy:
            messagebox.showinfo(
                "MorrowFriends is busy",
                "Another setup task is still running. Wait for it to finish, then try again.",
            )
            return

        btn = self._vc_widget("install_vc_runtime_btn")
        bar = self._vc_widget("vc_runtime_progress")
        if btn is not None:
            btn.configure(state="disabled", text="Installing…")
        self._set_vc_status("Downloading the official Microsoft installer…", "muted")
        self._note_recovery("Downloading the official Microsoft C++ installer…")
        if bar is not None:
            bar.configure(progress_color=COLORS["accent"])
            bar.set(0)
            bar.pack(anchor="w", fill="x", pady=(8, 0))

        def update_progress(msg: str) -> None:
            self.log(msg)
            progress = self._vc_widget("vc_runtime_progress")
            match = re.search(r"Downloading Microsoft C\+\+ runtime.*?(\d+)%", msg)
            if match:
                percent = int(match.group(1))
                if progress is not None:
                    progress.set(percent / 100)
                self._set_vc_status(
                    f"Downloading the official Microsoft installer… {percent}%",
                    "muted",
                )
                self._note_recovery(
                    f"Downloading the official Microsoft C++ installer… {percent}%"
                )
            elif msg.startswith("Download verified"):
                if progress is not None:
                    progress.set(1)
                self._set_vc_status(
                    "Download verified — approve the Windows installation prompt.",
                    "muted",
                )
                self._note_recovery(
                    "Download verified — approve the Windows installation prompt."
                )

        def finish_success(restart_required: bool) -> None:
            done_btn = self._vc_widget("install_vc_runtime_btn")
            if done_btn is not None:
                done_btn.configure(
                    state="disabled" if restart_required else "normal",
                    text="Restart Windows" if restart_required else "Install C++ component",
                )
            if restart_required:
                self._set_vc_status(
                    "Installed — restart Windows, reopen MorrowFriends, then join.",
                    "warn",
                )
                message = "Installation succeeded. Restart Windows before joining the game."
            else:
                self._refresh_vc_runtime_status()
                message = "The required Microsoft C++ component is installed. You can join now."
            self._note_recovery(message)
            messagebox.showinfo("C++ component installed", message)

        def finish_failure(detail: str) -> None:
            fail_btn = self._vc_widget("install_vc_runtime_btn")
            fail_bar = self._vc_widget("vc_runtime_progress")
            if fail_btn is not None:
                fail_btn.configure(state="normal", text="Try Install Again")
            if fail_bar is not None:
                fail_bar.configure(progress_color=COLORS["danger"])
            # See above: red fails AA as text on every ground in this theme.
            self._set_vc_status(f"Installation failed: {detail}", "warn")
            self._note_recovery(f"C++ install failed: {detail}")

        def work() -> None:
            def cb(msg: str) -> None:
                self.after(0, lambda m=msg: update_progress(m))

            try:
                restart_required = install_vc_runtime(cb)
            except Exception as exc:
                detail = str(exc)
                self.after(0, lambda message=detail: finish_failure(message))
                raise
            else:
                self.after(0, lambda restart=restart_required: finish_success(restart))

        self._run_bg(work)

    def _repair_engine(self) -> None:
        if self._busy:
            messagebox.showinfo(
                "MorrowFriends is busy",
                "Another setup task is still running. Wait for it to finish, then try Repair again.",
            )
            return

        # Same removed-cockpit hazard as the VC-runtime block above. "Fix this"
        # offers Repair TES3MP to friends, so these widgets are absent exactly
        # when a friend needs the button most. _note_recovery already mirrors
        # every message onto the Play screen, which is the surface they see.
        def _repair_status(message: str) -> None:
            var = self._vc_widget("engine_repair_status_var")
            if var is not None:
                var.set(message)
            self._note_recovery(message)

        def _repair_bar(**calls):
            bar = self._vc_widget("engine_repair_progress")
            if bar is None:
                return
            if "configure" in calls:
                bar.configure(**calls["configure"])
            if "set" in calls:
                bar.set(calls["set"])
            if calls.get("show"):
                bar.pack(anchor="w", fill="x", pady=(8, 0))

        def _repair_btn(**cfg):
            btn = self._vc_widget("repair_engine_btn")
            if btn is not None:
                btn.configure(**cfg)

        _repair_btn(state="disabled", text="Repairing…")
        _repair_status(f"Downloading a fresh TES3MP {TES3MP_VERSION}…")
        _repair_bar(configure={"progress_color": COLORS["accent"]}, set=0, show=True)

        def update_progress(msg: str) -> None:
            self.log(msg)
            match = re.search(r"Downloading TES3MP.*?(\d+)%", msg)
            if match:
                percent = int(match.group(1))
                _repair_bar(set=percent / 100)
                _repair_status(f"Downloading fresh TES3MP {TES3MP_VERSION}… {percent}%")
            elif msg.startswith("Extracting TES3MP"):
                _repair_bar(set=1)
                _repair_status("Download verified. Installing TES3MP…")

        def finish_success() -> None:
            _repair_btn(state="normal", text="Repair TES3MP")
            _repair_bar(set=1)
            _repair_status(f"TES3MP {TES3MP_VERSION} is ready. Press Play.")
            messagebox.showinfo(
                "TES3MP repair complete",
                f"TES3MP {TES3MP_VERSION} was downloaded, verified, and installed successfully.",
            )

        def finish_failure(detail: str) -> None:
            _repair_btn(state="normal", text="Try Repair Again")
            _repair_bar(configure={"progress_color": COLORS["danger"]})
            _repair_status(f"TES3MP repair failed: {detail}")

        def work() -> None:
            def cb(msg: str) -> None:
                self.after(0, lambda m=msg: update_progress(m))

            try:
                repair_tes3mp(cb)
            except Exception as exc:
                detail = str(exc)
                self.after(0, lambda message=detail: finish_failure(message))
                raise
            else:
                self.after(0, finish_success)

        self._run_bg(work)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
