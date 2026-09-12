"""MorrowFriends visual system — ash night, bone, and Red Mountain ember."""

from __future__ import annotations

# Bone is the primary-action inversion; ember carries live/warn state.
COLORS = {
    "bg": "#0a090b",
    "header": "#121014",
    "surface": "#16131a",
    "surface_low": "#07060a",
    "surface_raised": "#1c1822",
    "line": "#2a2530",
    "line_strong": "#4a3f4c",
    "accent": "#a63d3d",
    "accent_hover": "#bd5151",
    "accent_soft": "#3a2024",
    "ember": "#c45a3a",
    "ember_dim": "#6e3228",
    "primary": "#e6dccb",
    "primary_hover": "#f3ebe0",
    "text": "#f0ebe6",
    "secondary": "#c9bfb6",
    "muted": "#9c938c",
    "ok": "#8fbc7a",
    "warn": "#c9a05a",
    "danger": "#9d443c",
    "danger_hover": "#b35148",
    "gold": "#8e6c3d",
    "gold_hover": "#a6804a",
    "field": "#0e0c11",
    "field_border": "#3a3340",
    "button": "#1d1a22",
    "button_hover": "#2c2732",
    "button_inset": "#141118",
}

# Prefer expressive Windows faces; Tk falls back cleanly if missing.
FONTS = {
    "brand": ("Sitka Display", 26, "bold"),
    "brand_fallback": ("Georgia", 26, "bold"),
    "heading": ("Bahnschrift", 15, "normal"),
    "heading_fallback": ("Segoe UI Semibold", 15, "normal"),
    "label": ("Bahnschrift", 12, "normal"),
    "body": ("Bahnschrift", 15, "normal"),
    "button": ("Bahnschrift SemiBold", 13, "normal"),
    "button_fallback": ("Segoe UI Semibold", 13, "normal"),
    "mono": ("Cascadia Mono", 12, "normal"),
    "tiny": ("Bahnschrift", 10, "normal"),
    "tagline": ("Bahnschrift", 13, "normal"),
}


def ui_font(role: str, *, size: int | None = None, weight: str | None = None):
    """Build a CTkFont for a named role with a safe Windows fallback."""
    import customtkinter as ctk

    spec = FONTS.get(role, FONTS["body"])
    family, default_size, default_weight = spec
    fallback = FONTS.get(f"{role}_fallback")
    chosen = family
    try:
        # Probe availability without raising — CTk/Tk substitute silently,
        # but we prefer an explicit known face when the primary is absent.
        import tkinter.font as tkfont

        available = {name.casefold() for name in tkfont.families()}
        if family.casefold() not in available and fallback:
            chosen = fallback[0]
            if size is None:
                size = fallback[1]
            if weight is None:
                weight = fallback[2]
    except Exception:
        if fallback:
            chosen = fallback[0]
    return ctk.CTkFont(
        family=chosen,
        size=size if size is not None else default_size,
        weight=weight if weight is not None else default_weight,
    )
