"""Push-to-talk bindings shared by Settings and the voice page URL."""

from __future__ import annotations

from typing import Any


DEFAULT_PTT_BINDING = {"kind": "keyboard", "code": "Space", "label": "Space"}

_TK_KEYSYM_TO_CODE = {
    "space": "Space",
    "Return": "Enter",
    "KP_Enter": "Enter",
    "Tab": "Tab",
    "BackSpace": "Backspace",
    "Delete": "Delete",
    "Insert": "Insert",
    "Home": "Home",
    "End": "End",
    "Prior": "PageUp",
    "Next": "PageDown",
    "Left": "ArrowLeft",
    "Right": "ArrowRight",
    "Up": "ArrowUp",
    "Down": "ArrowDown",
    "Shift_L": "ShiftLeft",
    "Shift_R": "ShiftRight",
    "Control_L": "ControlLeft",
    "Control_R": "ControlRight",
    "Alt_L": "AltLeft",
    "Alt_R": "AltRight",
    "Pause": "Pause",
    "Caps_Lock": "CapsLock",
    "Print": "PrintScreen",
    "Num_Lock": "NumLock",
    "Scroll_Lock": "ScrollLock",
}

_CODE_LABELS = {
    "Space": "Space",
    "Escape": "Escape",
    "Enter": "Enter",
    "Tab": "Tab",
    "Backspace": "Backspace",
    "Delete": "Delete",
    "Insert": "Insert",
    "Home": "Home",
    "End": "End",
    "PageUp": "Page Up",
    "PageDown": "Page Down",
    "ArrowUp": "Up Arrow",
    "ArrowDown": "Down Arrow",
    "ArrowLeft": "Left Arrow",
    "ArrowRight": "Right Arrow",
    "ShiftLeft": "Left Shift",
    "ShiftRight": "Right Shift",
    "ControlLeft": "Left Ctrl",
    "ControlRight": "Right Ctrl",
    "AltLeft": "Left Alt",
    "AltRight": "Right Alt",
}

_MOUSE_LABELS = (
    "Left Mouse",
    "Middle Mouse",
    "Right Mouse",
    "Mouse Back",
    "Mouse Forward",
)


def ptt_label(kind: str, value: str) -> str:
    if kind == "mouse":
        try:
            index = int(value)
        except ValueError:
            return value
        if 0 <= index < len(_MOUSE_LABELS):
            return _MOUSE_LABELS[index]
        return f"Mouse {value}"
    if value in _CODE_LABELS:
        return _CODE_LABELS[value]
    if value.startswith("Key") and len(value) == 4:
        return value[3]
    if value.startswith("Digit") and len(value) == 6:
        return value[5]
    if value.startswith("Numpad"):
        return f"Numpad {value[6:]}"
    if value.startswith("F") and value[1:].isdigit():
        return value
    return value


def normalize_ptt_binding(value: Any) -> dict[str, Any] | None:
    """Same rules as voice_service/static/app.js validBinding()."""
    if not isinstance(value, dict):
        return None
    label = value.get("label")
    if not isinstance(label, str) or not (1 <= len(label) <= 40):
        return None
    kind = value.get("kind")
    if kind == "keyboard":
        code = value.get("code")
        if not isinstance(code, str) or not code.isalnum() or len(code) > 32:
            return None
        return {"kind": "keyboard", "code": code, "label": label}
    if kind == "mouse":
        button = value.get("button")
        if not isinstance(button, int) or button < 0 or button > 4:
            return None
        return {"kind": "mouse", "button": button, "label": label}
    return None


def ptt_wire_value(binding: dict[str, Any]) -> str:
    if binding.get("kind") == "mouse":
        return str(binding["button"])
    return str(binding.get("code") or "Space")


def binding_from_tk_key(keysym: str) -> dict[str, Any] | None:
    """Map a Tk keysym to the page's KeyboardEvent.code binding. Escape is cancel."""
    if not keysym or keysym == "Escape":
        return None
    code = _TK_KEYSYM_TO_CODE.get(keysym)
    if code is None and len(keysym) == 1 and keysym.isalpha():
        code = f"Key{keysym.upper()}"
    elif code is None and len(keysym) == 1 and keysym.isdigit():
        code = f"Digit{keysym}"
    elif code is None and keysym.startswith("F") and keysym[1:].isdigit():
        number = int(keysym[1:])
        if 1 <= number <= 24:
            code = f"F{number}"
    if code is None or not code.isalnum() or len(code) > 32:
        return None
    return {"kind": "keyboard", "code": code, "label": ptt_label("keyboard", code)}


def binding_from_tk_mouse(num: int) -> dict[str, Any] | None:
    """Tk Button-1/2/3 → browser button 0/1/2. Scroll wheels are ignored."""
    if num not in {1, 2, 3}:
        return None
    button = num - 1
    return {
        "kind": "mouse",
        "button": button,
        "label": ptt_label("mouse", str(button)),
    }
