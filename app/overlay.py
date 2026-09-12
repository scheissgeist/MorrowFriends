"""Always-on-top nearby strip so voice and /goto stay in reach during play."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from .theme import COLORS, ui_font


class NearbyStrip(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        names_source: Callable[[], list[str]],
        goto_callback: Callable[[str], None] | None = None,
        ptt_source: Callable[[], bool] | None = None,
        voice_names_source: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__(master)
        self.names_source = names_source
        self.goto_callback = goto_callback
        self.ptt_source = ptt_source
        # Who is actually in VOICE, which is not the same as who is in the
        # game. Without this the strip lists the game roster and gives no way
        # to tell whether someone can hear you.
        self.voice_names_source = voice_names_source
        self._voice_names: set[str] = set()
        self._voice_tick = 0
        self.title("MorrowFriends nearby")
        self.geometry("460x96")
        self.minsize(420, 88)
        self.configure(fg_color=COLORS["surface"])
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        tk.Frame(
            self, bg=COLORS["ember"], height=2, bd=0, highlightthickness=0
        ).pack(fill="x")
        header = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        header.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            header,
            text="Nearby",
            font=ui_font("heading", size=14),
            text_color=COLORS["text"],
        ).pack(side="left")
        self.ptt_var = tk.StringVar(value="Voice ready")
        self.ptt_label = ctk.CTkLabel(
            header,
            textvariable=self.ptt_var,
            font=ui_font("tiny"),
            text_color=COLORS["muted"],
        )
        self.ptt_label.pack(side="right")

        self.row = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.row.pack(fill="x", padx=8, pady=(8, 10))
        self._refresh()

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        talking = bool(self.ptt_source and self.ptt_source())

        # Refresh the voice roster every ~5s. The relay is a network call, so
        # it must not run on the 1s UI tick.
        if self.voice_names_source is not None and self._voice_tick % 5 == 0:
            try:
                self._voice_names = {
                    name.casefold() for name in self.voice_names_source() if name
                }
            except Exception:
                pass
        self._voice_tick += 1

        if talking:
            self.ptt_var.set("Talking")
            self.ptt_label.configure(text_color=COLORS["ember"])
        elif self._voice_names:
            self.ptt_var.set(f"Voice on · {len(self._voice_names)} in party")
            self.ptt_label.configure(text_color=COLORS["muted"])
        else:
            # Say voice is DOWN rather than implying it is merely idle. On
            # 2026-08-18 voice broke four times and the strip kept reading
            # "Hold PTT to talk", which looks identical to working-but-quiet.
            self.ptt_var.set("Voice offline")
            self.ptt_label.configure(text_color=COLORS["warn"])
        for child in self.row.winfo_children():
            child.destroy()
        names = []
        try:
            names = [name for name in self.names_source() if name]
        except Exception:
            names = []
        if not names:
            ctk.CTkLabel(
                self.row,
                text="Waiting for the party…",
                text_color=COLORS["muted"],
                font=ui_font("tiny"),
            ).pack(side="left", padx=4)
        else:
            for name in names[:6]:
                in_voice = name.casefold() in self._voice_names
                width = max(88, min(148, 16 + len(name) * 8))
                ctk.CTkButton(
                    self.row,
                    # A mark means they are in voice; a plain name is in the
                    # game but cannot hear you.
                    text=f"· {name}" if in_voice else name,
                    width=width,
                    height=30,
                    corner_radius=0,
                    fg_color=COLORS["accent_soft"] if in_voice else COLORS["button"],
                    hover_color=COLORS["button_hover"],
                    text_color=COLORS["text"] if in_voice else COLORS["muted"],
                    font=ui_font("tiny"),
                    command=lambda n=name: self._goto(n),
                ).pack(side="left", padx=3)
        self.after(1000, self._refresh)

    def _goto(self, name: str) -> None:
        if self.goto_callback is not None:
            self.goto_callback(name)
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(f"/goto {name}")
            self.ptt_var.set(f"Copied /goto {name}")
        except Exception:
            return
