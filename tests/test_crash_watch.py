import unittest

from app.crash_watch import CRASH_WINDOW_SECONDS, classify_process_exit


class _FakeProc:
    def __init__(self, code: int | None) -> None:
        self._code = code

    def poll(self) -> int | None:
        return self._code


class CrashWatchTests(unittest.TestCase):
    def test_running_process_is_not_an_exit(self) -> None:
        self.assertIsNone(
            classify_process_exit(_FakeProc(None), started_at=0.0, now=3.0)
        )

    def test_quick_death_asks_for_repair(self) -> None:
        result = classify_process_exit(
            _FakeProc(1),
            started_at=0.0,
            now=CRASH_WINDOW_SECONDS - 1,
            tes3mp_ok=True,
            vc_ok=True,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "crash")
        self.assertEqual(result.action, "repair")

    def test_quick_death_without_vc_asks_for_runtime(self) -> None:
        result = classify_process_exit(
            _FakeProc(1),
            started_at=0.0,
            now=2.0,
            tes3mp_ok=True,
            vc_ok=False,
        )
        self.assertEqual(result.action, "vc")

    def test_later_close_is_not_treated_as_a_crash(self) -> None:
        result = classify_process_exit(
            _FakeProc(0),
            started_at=0.0,
            now=CRASH_WINDOW_SECONDS + 5,
        )
        self.assertEqual(result.kind, "closed")
        self.assertEqual(result.action, "")


if __name__ == "__main__":
    unittest.main()
