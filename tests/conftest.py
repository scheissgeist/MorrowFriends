"""Shared pytest fixtures."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _no_real_protocol_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from rewriting the developer's morrowfriends:// handler.

    App.__init__ calls register_protocol(), which writes
    HKCU\\Software\\Classes\\morrowfriends. Any test that constructs App()
    therefore re-pointed the real handler at the test interpreter: after a
    pytest run on 2026-10-01 invite links opened .venv\\Scripts\\python.exe
    instead of the installed launcher.

    This must not import app.main: doing so before every test made
    test_voice_end_to_end time out on its websocket handshake in 2 of 4 full
    runs (0 of 4 without). Patch the light app.deeplink module, which app.main
    binds from when it is first imported, and app.main only if already loaded.
    """
    import app.deeplink

    monkeypatch.setattr(app.deeplink, "register_protocol", lambda: False)
    main = sys.modules.get("app.main")
    if main is not None:
        monkeypatch.setattr(main, "register_protocol", lambda: False)
