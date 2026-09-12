import unittest
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "voice_service" / "static"


class VoiceWebTests(unittest.TestCase):
    def test_page_pins_livekit_and_has_no_inline_script(self) -> None:
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("livekit-client@2.21.0", html)
        self.assertIn('src="assets/app.js"', html)
        self.assertNotIn("MORROWVOICE_HOST_TOKEN", html)
        self.assertNotIn("<script>", html)

    def test_client_is_push_to_talk_and_fails_closed_on_stale_positions(self) -> None:
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('"v1/claim"', script)
        self.assertIn("v1/auto-claim", script)
        self.assertIn("tryAutomaticJoin", script)
        self.assertIn("setMicrophoneEnabled(false)", script)
        self.assertIn('window.localStorage.setItem("morrowvoice.pttBinding"', script)
        self.assertIn("function bindingFromLink()", script)
        self.assertIn('params.get("ptt_kind")', script)
        self.assertIn('kind: "keyboard", code: "Space"', script)
        self.assertIn('kind: "mouse", button: event.button', script)
        self.assertIn("function finishBindingCapture(binding)", script)
        self.assertIn('new URL("http://127.0.0.1:47981/v1/ptt/events")', script)
        self.assertIn("new EventSource(url)", script)
        self.assertIn("function muteAll(reason)", script)
        self.assertIn('panner.panningModel = "HRTF"', script)
        self.assertIn("createMediaStreamSource", script)
        self.assertIn('element.dataset.spatialAudio = "true"', script)
        self.assertIn("element.volume = 0", script)
        self.assertIn("acousticProfiles", script)
        self.assertIn('"large-interior"', script)
        self.assertIn("graph.convolver.buffer = impulseFor", script)
        self.assertIn("position.right", script)
        self.assertIn("async function resetPartialJoin()", script)
        self.assertIn("MorrowFriends will try again after you finish logging in", script)
        self.assertIn("performance.now() - lastMixAt > 2500", script)
        self.assertNotIn("host_token", script)

    def test_enable_sound_appears_when_the_spatial_context_is_suspended(self) -> None:
        """The HRTF graph is the only audible path, so canPlaybackAudio lies.

        MorrowFriends opens this page with ?auto=1, so joinVoice() runs with no
        user gesture and the AudioContext starts suspended. The LiveKit elements
        are muted on purpose and muted elements always satisfy autoplay, so
        room.canPlaybackAudio reported healthy and the one button that resumes
        the context stayed hidden — connected, metered, and totally silent.
        """
        script = (STATIC / "app.js").read_text(encoding="utf-8")

        self.assertIn("function audioIsBlocked()", script)
        self.assertIn('spatialAudioContext.state !== "running"', script)
        self.assertIn("if (room && !room.canPlaybackAudio) return true;", script)
        self.assertIn(
            'enableAudioButton.classList.toggle("hidden", !audioIsBlocked());', script
        )
        # The old gate hid the button whenever LiveKit was happy. It must never
        # come back in any form.
        self.assertNotIn(
            'enableAudioButton.classList.toggle("hidden", room.canPlaybackAudio)', script
        )
        self.assertNotIn('enableAudioButton.classList.add("hidden")', script)

        # A suspended context must also self-heal on any later gesture, and the
        # watchdog re-evaluates the gate so it cannot get stuck hidden.
        self.assertIn("function unlockAudioOnGesture()", script)
        self.assertIn('window.addEventListener("pointerdown", unlockAudioOnGesture, true)', script)
        self.assertIn('spatialAudioContext.addEventListener("statechange", refreshAudioGate)', script)
        self.assertIn("refreshAudioGate();\n  }, 500);", script)

    def test_auto_join_retries_instead_of_stranding_the_page(self) -> None:
        """Claims are one-time-use, so an attempt between claims must retry."""
        script = (STATIC / "app.js").read_text(encoding="utf-8")

        self.assertIn("function scheduleJoinRetry()", script)
        self.assertIn("joinRetryTimer = window.setTimeout(tryAutomaticJoin, delayMs)", script)
        self.assertIn("if (sessionActive) return;", script)
        self.assertNotIn("Waiting for your character to finish loading", script)

    def test_the_page_does_not_ask_who_you_are(self) -> None:
        """A typed launcher name is identity. An empty name waits for chargen.

        Never offer the party list. /health includes everyone, so picking or
        guessing from it is how a visitor claimed the host. A new character is
        the one name that appears after this page opened.
        """
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("Who are you", html)
        self.assertNotIn("character-picker", html)
        self.assertNotIn("Have a join code", html)
        self.assertNotIn("claim-code", html)
        self.assertNotIn("claim-form", html)
        self.assertNotIn("showCharacterPicker", script)
        self.assertNotIn("Pick who you are", script)
        self.assertNotIn("linkClaimAttempts", script)
        self.assertIn("Waiting for ${playerFromLink} to finish logging in", script)
        self.assertIn("Never guess from the party list", script)
        self.assertIn("namesAtOpen", script)
        self.assertIn("arrived.length === 1", script)
        self.assertIn("Waiting for your character to finish logging in", script)
        self.assertIn("5000 * (2 ** Math.min(joinRetryFailures - 1, 3))", script)

    def test_a_dropped_relay_session_reattaches_itself(self) -> None:
        """A relay restart loses every session; 4401 must not strand the page."""
        script = (STATIC / "app.js").read_text(encoding="utf-8")

        self.assertIn("resetPartialJoin().then(tryAutomaticJoin);", script)
        self.assertNotIn("Rejoin with a new /voice code", script)

    def test_page_keeps_the_ash_plaque(self) -> None:
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("/voice", html)
        self.assertNotIn("#d4a34c", css)
        self.assertIn("--ember: #c45a3a", css)


if __name__ == "__main__":
    unittest.main()
