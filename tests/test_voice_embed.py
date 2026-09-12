import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice_embed import VoiceEmbedder, webview2_available  # noqa: E402


class VoiceEmbedGuardTests(unittest.TestCase):
    """The embedder must fail into the separate-window fallback, never upward.

    A launcher that will not start is far worse than a voice window that opens
    beside it, so every failure path here has to return a result rather than
    raise.
    """

    def test_an_insecure_page_is_refused_before_anything_is_created(self) -> None:
        result = VoiceEmbedder().start(None, "http://voice.example.test/")
        self.assertFalse(result.ok)
        self.assertIn("https", result.detail)

    def test_a_missing_webview2_runtime_reports_failure_instead_of_raising(self) -> None:
        with patch("app.voice_embed.webview2_available", return_value=False):
            result = VoiceEmbedder().start(None, "https://voice.example.test/")
        self.assertFalse(result.ok)
        self.assertIn("WebView2", result.detail)

    def test_stopping_something_that_never_started_is_harmless(self) -> None:
        embedder = VoiceEmbedder()
        embedder.stop()
        embedder.stop()
        self.assertFalse(embedder.embedded)

    def test_fit_without_a_view_does_nothing(self) -> None:
        embedder = VoiceEmbedder()
        embedder.fit()
        self.assertFalse(embedder.embedded)

    def test_availability_is_a_bool_and_never_throws(self) -> None:
        self.assertIsInstance(webview2_available(), bool)


class VoiceClientFallbackContractTests(unittest.TestCase):
    def test_the_dead_pywebview_branch_is_gone(self) -> None:
        """It could never succeed on a Tk main thread, and it reported success
        anyway, so the first Open voice click opened nothing."""
        source = (
            Path(__file__).resolve().parents[1] / "app" / "voice_client.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("_ensure_webview_window", source)
        self.assertNotIn("webview.start", source)


class LauncherVoiceAndOverlayContracts(unittest.TestCase):
    def test_goto_does_not_sleep_on_the_tk_thread(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("threading.Thread(target=worker, daemon=True).start()", source)
        self.assertIn('send_chat_command(f"/goto {name}")', source)

    def test_a_failed_embed_is_not_retried(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._voice_embed_failed", source)
        self.assertIn("if not self._voice_embed_failed and self._show_voice_view(url):", source)

    def test_embed_start_never_raises_out_of_the_module(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "voice_embed.py"
        ).read_text(encoding="utf-8")
        self.assertIn("return self._start(container, url)", source)
        self.assertIn("return EmbedResult(False, f\"{type(exc).__name__}: {exc}\")", source)

    def test_play_learns_the_name_from_this_client_not_the_party(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text(encoding="utf-8")
        start = source.index("def _finish_play_session")
        apply_at = source.index("def _apply_local_login_name")
        body = source[start:apply_at]
        self.assertIn("local_login_name(since=since)", source)
        self.assertIn("self._open_voice_client()", body)
        self.assertNotIn("attach_voice(", source[start:source.index("def _show_nearby_strip")])
        self.assertIn("load_voice_enabled()", body)
        self.assertIn("Voice is off.", body)
        self.assertNotIn("fetch_party_names", source[start:source.index("def _show_nearby_strip")])
        self.assertIn("Never from the party list", source[apply_at:apply_at + 400])
        apply_body = source[apply_at:source.index("def _show_nearby_strip")]
        self.assertIn("self._open_voice_client()", apply_body)
        self.assertNotIn("open_voice_client(url=", apply_body)

    def test_secondary_buttons_size_to_their_label(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _chip_width", source)
        self.assertIn("if width is None:", source)
        self.assertNotIn('path_row, "Change…"', source)
        self.assertNotIn("width=118", source)
        self.assertNotIn("width=86, height=34", source)
        self.assertNotIn("width=86, height=35", source)

    def test_settings_lives_in_this_window(self) -> None:
        """A second Toplevel is what Windows sent behind Play."""
        source = (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text(encoding="utf-8")
        start = source.index("def _build_settings_view")
        end = source.index("def _apply_atmosphere")
        body = source[start:end]
        self.assertNotIn("ctk.CTkToplevel", body)
        self.assertNotIn("_settings_window", body)
        self.assertIn("self.friend_play.pack_forget()", body)
        self.assertNotIn("self._play_panel.pack_forget()", body)
        self.assertIn("def _hide_settings_view", body)
        self.assertIn("self._settings_view.pack(", body)
        self.assertIn("self._back_btn.pack(side=\"left\")", body)


class SettingsSwapTests(unittest.TestCase):
    def test_gear_swaps_the_play_body_in_this_window(self) -> None:
        from app.main import App

        app = App()
        try:
            app.update()
            play_size = app.geometry().split("+", 1)[0]
            self.assertTrue(app.friend_play.winfo_ismapped())
            self.assertFalse(app._back_btn.winfo_ismapped())
            app._show_settings()
            app.update()
            self.assertFalse(app.friend_play.winfo_ismapped())
            self.assertTrue(app._settings_view.winfo_ismapped())
            self.assertTrue(app._back_btn.winfo_ismapped())
            self.assertFalse(app.settings_btn.winfo_ismapped())
            version = next(
                child
                for child in app._back_btn.master.winfo_children()
                if str(child.cget("text")).startswith("v")
            )
            self.assertLess(version.winfo_x(), app._back_btn.winfo_x())
            app._start_ptt_capture(
                app._ptt_label_var, app._ptt_status_var, app._ptt_btn
            )
            self.assertTrue(app._ptt_capturing)
            app._hide_settings_view()
            app.update()
            self.assertFalse(app._ptt_capturing)
            self.assertTrue(app.friend_play.winfo_ismapped())
            self.assertFalse(app._settings_view.winfo_ismapped())
            self.assertTrue(app.settings_btn.winfo_ismapped())
            self.assertEqual(app.geometry().split("+", 1)[0], play_size)
        finally:
            app._on_close()


if __name__ == "__main__":
    unittest.main()
