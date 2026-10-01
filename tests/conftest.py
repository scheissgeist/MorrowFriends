"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_protocol_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from rewriting the developer's morrowfriends:// handler.

    App.__init__ calls register_protocol(), which writes
    HKCU\\Software\\Classes\\morrowfriends. Any test that constructs App()
    therefore re-pointed the real handler at the test interpreter: after a
    pytest run on 2026-10-01 invite links opened .venv\\Scripts\\python.exe
    instead of the installed launcher. app.deeplink.register_protocol itself
    is left untouched for tests that exercise it directly.
    """
    import app.main

    monkeypatch.setattr(app.main, "register_protocol", lambda: False)
