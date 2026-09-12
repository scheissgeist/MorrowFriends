"""Host the proximity voice page inside the launcher window itself.

Why this exists
---------------
The voice client is a web app: LiveKit's WebRTC stack, the HRTF panner and the
convolver reverb all live in `voice_service/static/app.js` and need a browser
engine. Tkinter has neither WebRTC nor an audio pipeline, so the UI cannot be
reimplemented natively.

`voice_client.open_voice_client` therefore opened a SEPARATE window. pywebview
was meant to supply it, but pywebview 5 raises "pywebview must be run on a main
thread" and the launcher's main thread is already Tk's event loop, so that path
has never actually worked — every user has silently been getting the Edge
`--app` fallback, i.e. a second window owned by a second process.

This module hosts a WebView2 control directly instead. It creates a borderless
WinForms form on its own STA thread and reparents that form's HWND into a Tk
frame, so the page renders inside the launcher with no title bar of its own.

The WebView2 assemblies come from pywebview, which is already a dependency, so
this adds nothing new to ship.

Everything here is best-effort: any failure returns False and the caller falls
back to the separate window, because a missing voice window is recoverable and a
launcher that will not start is not.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .paths import local_app_data

# --- Win32 -----------------------------------------------------------------

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOZORDER = 0x0004

_user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None

if _user32 is not None:
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.SetParent.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    # The Ptr variants are required on 64-bit or the style word is truncated.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _get_style = _user32.GetWindowLongPtrW
        _set_style = _user32.SetWindowLongPtrW
        _get_style.restype = ctypes.c_ssize_t
        _set_style.restype = ctypes.c_ssize_t
        _get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        _set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    else:
        _get_style = _user32.GetWindowLongW
        _set_style = _user32.SetWindowLongW

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _find_window_by_title(title: str) -> int | None:
    """Top-level window with this exact title, anywhere in the session.

    The form is created on a .NET thread, so its handle is not available to us
    synchronously; matching a private title is simpler than marshalling it back.
    """
    if _user32 is None:
        return None
    hit: list[int] = []

    def callback(hwnd, _lparam):
        length = _user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == title:
                hit.append(hwnd)
                return False
        return True

    _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    return hit[0] if hit else None


def _webview_lib_dir() -> Path | None:
    """Where pywebview keeps the WebView2 assemblies, frozen or not."""
    frozen = Path(getattr(sys, "_MEIPASS", "")) / "webview" / "lib"
    if frozen.is_dir():
        return frozen
    try:
        import webview
    except ImportError:
        return None
    candidate = Path(webview.__file__).parent / "lib"
    return candidate if candidate.is_dir() else None


def webview2_available() -> bool:
    """True when the pieces needed to embed are all present."""
    if os.name != "nt":
        return False
    lib = _webview_lib_dir()
    if lib is None:
        return False
    if not (lib / "Microsoft.Web.WebView2.WinForms.dll").is_file():
        return False
    try:
        import clr  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class EmbedResult:
    ok: bool
    detail: str


class VoiceEmbedder:
    """A WebView2 control living inside a Tk frame.

    One instance per launcher. `start()` is idempotent: calling it again just
    navigates the existing view, which is what reopening voice should do.
    """

    # Private, unique, and never shown to the user: the form is borderless, so
    # this title exists only so we can find the HWND to reparent.
    _WINDOW_TITLE = "MorrowFriendsVoiceEmbeddedHost"

    def __init__(self) -> None:
        self._form = None
        self._view = None
        self._child_hwnd: int | None = None
        self._container = None
        self._container_hwnd: int | None = None
        self._thread = None
        self._ready = threading.Event()
        self._error: str = ""
        self._attached = False
        self._clr_ready = False

    # -- public ------------------------------------------------------------

    @property
    def embedded(self) -> bool:
        return bool(
            self._child_hwnd
            and _user32 is not None
            and _user32.IsWindow(self._child_hwnd)
        )

    def start(self, container, url: str) -> EmbedResult:
        """Create or reuse the embedded view inside `container` (a Tk widget)."""
        try:
            return self._start(container, url)
        except Exception as exc:  # noqa: BLE001 — CLR faults must not kill Tk
            return EmbedResult(False, f"{type(exc).__name__}: {exc}")

    def _start(self, container, url: str) -> EmbedResult:
        if not url.startswith("https://") and not url.startswith("file:"):
            return EmbedResult(False, "Voice page must be an https:// URL")
        if not webview2_available():
            return EmbedResult(False, "WebView2 is not available on this PC")

        if self.embedded:
            self.navigate(url)
            return EmbedResult(True, "Voice is already open in the window.")

        self._container = container
        try:
            container.update_idletasks()
            self._container_hwnd = container.winfo_id()
        except Exception as exc:
            return EmbedResult(False, f"Could not resolve the panel window: {exc}")

        try:
            self._ensure_clr()
        except Exception as exc:  # noqa: BLE001
            return EmbedResult(False, f"WebView2 assemblies unavailable: {exc}")

        if self._thread is None:
            self._error = ""
            self._ready.clear()
            from System.Threading import ApartmentState, Thread as NetThread, ThreadStart

            # MUST be a .NET STA thread. WebView2 creates its environment through
            # COM, and on a plain Python thread (which the CLR joins as MTA)
            # CreateAsync fails with RPC_E_CHANGED_MODE, "cannot change thread
            # mode after it is set".
            thread = NetThread(ThreadStart(lambda: self._run_forms(url)))
            thread.SetApartmentState(ApartmentState.STA)
            thread.IsBackground = True
            thread.Start()
            self._thread = thread

        # The form is built on another thread; wait briefly for it to exist.
        if not self._ready.wait(timeout=20.0):
            return EmbedResult(False, self._error or "Voice view did not start in time")
        if self._error:
            return EmbedResult(False, self._error)
        return self._attach()

    def navigate(self, url: str) -> None:
        view = self._view
        if view is None:
            return
        try:
            from System import Uri

            # Source must be set on the UI thread that owns the control.
            self._invoke(lambda: setattr(view, "Source", Uri(url)))
        except Exception:
            pass

    def fit(self) -> None:
        """Resize the child to the container. Bind this to <Configure>."""
        if not self.embedded or self._container is None:
            return
        try:
            width = max(int(self._container.winfo_width()), 1)
            height = max(int(self._container.winfo_height()), 1)
        except Exception:
            return
        _user32.SetWindowPos(
            self._child_hwnd, None, 0, 0, width, height,
            SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOZORDER,
        )

    def stop(self) -> None:
        """Tear the view down. Safe to call when nothing was ever started."""
        self._detach_input()
        form = self._form
        self._child_hwnd = None
        if form is None:
            return
        try:
            form.BeginInvoke(_CloseDelegate(form))
        except Exception:
            try:
                form.Close()
            except Exception:
                pass
        self._form = None
        self._view = None
        self._thread = None
        self._ready.clear()

    # -- internals ---------------------------------------------------------

    def _invoke(self, fn) -> None:
        """Run fn on the WinForms thread; fall back to direct call."""
        form = self._form
        if form is None:
            fn()
            return
        try:
            if form.InvokeRequired:
                form.BeginInvoke(_ActionDelegate(fn))
                return
        except Exception:
            pass
        fn()

    def _ensure_clr(self) -> None:
        """Load the WebView2 assemblies once, on the caller's thread."""
        if self._clr_ready:
            return
        lib = _webview_lib_dir()
        if lib is None:
            raise RuntimeError("pywebview's WebView2 assemblies were not found")
        native = lib / "runtimes" / (
            "win-x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "win-x86"
        ) / "native"
        if native.is_dir():
            try:
                os.add_dll_directory(str(native))
            except OSError:
                pass
        if str(lib) not in sys.path:
            sys.path.append(str(lib))

        import clr

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        clr.AddReference(str(lib / "Microsoft.Web.WebView2.Core.dll"))
        clr.AddReference(str(lib / "Microsoft.Web.WebView2.WinForms.dll"))
        self._clr_ready = True

    def _run_forms(self, url: str) -> None:
        try:
            from Microsoft.Web.WebView2.Core import (
                CoreWebView2PermissionKind,
                CoreWebView2PermissionState,
            )
            from Microsoft.Web.WebView2.WinForms import (
                CoreWebView2CreationProperties,
                WebView2,
            )
            from System import Uri
            from System.Drawing import Color
            from System.Windows.Forms import Application, DockStyle, Form, FormBorderStyle

            form = Form()
            form.Text = self._WINDOW_TITLE
            # 'None' is a Python keyword; the enum member needs getattr.
            form.FormBorderStyle = getattr(FormBorderStyle, "None")
            form.ShowInTaskbar = False
            form.BackColor = Color.FromArgb(28, 23, 18)
            form.Width, form.Height = 480, 720

            view = WebView2()
            view.Dock = DockStyle.Fill
            props = CoreWebView2CreationProperties()
            # Default is beside the executable, which is read-only under
            # Program Files and makes the control fail to initialise.
            props.UserDataFolder = str(_user_data_folder())
            view.CreationProperties = props

            def on_initialized(_sender, args):
                if not args.IsSuccess:
                    reason = ""
                    try:
                        reason = str(args.InitializationException)
                    except Exception:
                        pass
                    self._error = f"WebView2 failed to initialise: {reason}"
                    return
                core = view.CoreWebView2

                def on_permission(_s, perm_args):
                    # Voice is the entire point of this window, so a modal
                    # microphone prompt inside an embedded panel is just a way
                    # to fail silently. Grant mic, refuse everything else.
                    if perm_args.PermissionKind == CoreWebView2PermissionKind.Microphone:
                        perm_args.State = CoreWebView2PermissionState.Allow
                    else:
                        perm_args.State = CoreWebView2PermissionState.Deny

                core.PermissionRequested += on_permission
                core.Settings.AreDefaultContextMenusEnabled = False
                core.Settings.IsStatusBarEnabled = False

            view.CoreWebView2InitializationCompleted += on_initialized
            form.Controls.Add(view)
            view.Source = Uri(url)

            self._form = form
            self._view = view
            form.CreateControl()
            # Handle must exist before the Tk side can find and reparent it.
            _ = form.Handle
            form.Show()
            self._ready.set()
            Application.Run(form)
        except Exception as exc:  # noqa: BLE001 - any failure means "fall back"
            self._error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
        finally:
            self._form = None
            self._view = None

    def _attach(self) -> EmbedResult:
        hwnd = None
        for _ in range(40):
            hwnd = _find_window_by_title(self._WINDOW_TITLE)
            if hwnd:
                break
            threading.Event().wait(0.05)
        if not hwnd:
            return EmbedResult(False, "Could not find the voice view to embed")

        style = (_get_style(hwnd, GWL_STYLE) & ~WS_POPUP) | WS_CHILD | WS_VISIBLE
        _set_style(hwnd, GWL_STYLE, style)
        ctypes.set_last_error(0)
        if not _user32.SetParent(hwnd, self._container_hwnd):
            return EmbedResult(
                False, f"SetParent failed (error {ctypes.get_last_error()})"
            )
        self._child_hwnd = hwnd
        self.fit()
        self._attach_input()
        return EmbedResult(True, "Voice is open in the MorrowFriends window.")

    def _attach_input(self) -> None:
        """Share input state with the WebView2 thread so typing reaches it."""
        if self._container is None or not self._child_hwnd:
            return
        try:
            tk_thread = _user32.GetWindowThreadProcessId(
                self._container.winfo_toplevel().winfo_id(), None
            )
            view_thread = _user32.GetWindowThreadProcessId(self._child_hwnd, None)
            self._attached = bool(
                _user32.AttachThreadInput(tk_thread, view_thread, True)
            )
        except Exception:
            self._attached = False

    def _detach_input(self) -> None:
        if not self._attached or self._container is None or not self._child_hwnd:
            self._attached = False
            return
        try:
            tk_thread = _user32.GetWindowThreadProcessId(
                self._container.winfo_toplevel().winfo_id(), None
            )
            view_thread = _user32.GetWindowThreadProcessId(self._child_hwnd, None)
            _user32.AttachThreadInput(tk_thread, view_thread, False)
        except Exception:
            pass
        self._attached = False


def _user_data_folder() -> Path:
    folder = local_app_data() / "webview2"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder


class _ActionDelegate:
    """Marshals a Python callable onto the WinForms thread."""

    def __new__(cls, fn):
        from System import Action

        return Action(fn)


class _CloseDelegate:
    def __new__(cls, form):
        from System import Action

        return Action(form.Close)
