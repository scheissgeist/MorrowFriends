import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_patcher():
    path = Path(__file__).resolve().parents[1] / "packaging" / "patch_packetreader.py"
    spec = importlib.util.spec_from_file_location("patch_packetreader", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PATCHER = _load_patcher()

SAMPLE = """            if isObjectPlayer then
                pid = tes3mp.GetObjectPid(packetIndex)
                player = Players[pid]
            else
                object = {}
            end
        elseif player ~= nil then
            packetTables.players[pid] = player
        end
"""


class PacketReaderPatchTests(unittest.TestCase):
    def test_the_patch_is_idempotent_and_inserts_both_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packetReader.lua"
            path.write_text(SAMPLE, encoding="utf-8")
            first = PATCHER.apply(path)
            second = PATCHER.apply(path)
            self.assertIn("patched", first)
            self.assertEqual(second, "already patched")
            text = path.read_text(encoding="utf-8")
            self.assertIn("if player == nil then", text)
            self.assertIn("Players[pid] ~= nil", text)
            self.assertTrue(any(path.parent.glob("packetReader.lua.bak.*")))


if __name__ == "__main__":
    unittest.main()
