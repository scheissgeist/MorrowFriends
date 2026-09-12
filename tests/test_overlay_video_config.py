"""Exclusive fullscreen hides every overlay, so the profile must not use it.

TES3MP's Lua API exposes only modal MessageBox dialogs — no HUD, no per-frame
draw hook — so an always-on-top window is the ONLY way to show voice state
during play, and it cannot appear over exclusive fullscreen.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import ensure_overlay_friendly_video


def _write(body: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "settings.cfg"
    path.write_text(body, encoding="utf-8")
    return path


class EnsureOverlayFriendlyVideoTests(unittest.TestCase):
    def test_exclusive_fullscreen_is_turned_off(self):
        path = _write("[General]\nencoding = win1252\n\n[Video]\nfullscreen = true\n")
        self.assertTrue(ensure_overlay_friendly_video(path))
        self.assertIn("fullscreen = false", path.read_text(encoding="utf-8"))

    def test_is_idempotent(self):
        path = _write("[Video]\nfullscreen = false\nwindow border = false\n")
        self.assertFalse(ensure_overlay_friendly_video(path))

    def test_other_settings_are_preserved(self):
        path = _write(
            "[Video]\nfullscreen = true\nvsync = 1\nresolution x = 2560\n\n"
            "[Game]\nshow owned = 1\n"
        )
        ensure_overlay_friendly_video(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("vsync = 1", text)
        self.assertIn("resolution x = 2560", text)
        self.assertIn("show owned = 1", text)

    def test_missing_video_section_is_added(self):
        path = _write("[General]\nencoding = win1252\n")
        self.assertTrue(ensure_overlay_friendly_video(path))
        text = path.read_text(encoding="utf-8")
        self.assertIn("[Video]", text)
        self.assertIn("fullscreen = false", text)

    def test_absent_file_is_not_an_error(self):
        self.assertFalse(ensure_overlay_friendly_video(Path(tempfile.mkdtemp()) / "nope.cfg"))


if __name__ == "__main__":
    unittest.main()
