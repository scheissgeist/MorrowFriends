from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.engine import (
    REQUIRED_TES3MP_PATHS,
    VC_RUNTIME_DLLS,
    _client_launch_command,
    _extract_zip,
    _valid_tes3mp_zip,
    install_vc_runtime,
    repair_tes3mp,
    save_server_state,
    tes3mp_ready,
    vc_runtime_ready,
)
from app.detect import MorrowindInstall
from app.config import ensure_native_openmw_profile
from app.packs import VANILLA
from app.paths import VC_RUNTIME_DOWNLOAD_URL


class EngineRepairTests(unittest.TestCase):
    def test_server_save_waits_for_matching_success_acknowledgement(self) -> None:
        sent: dict = {}

        def write_command(_root, command):
            sent.update(command)

        def read_result(_root):
            return {
                "requestId": sent.get("requestId"),
                "ok": True,
                "detail": 3,
            }

        messages: list[str] = []
        with patch("app.engine.tes3mp_dir", return_value=Path("C:/fake/tes3mp")), patch(
            "app.engine.write_host_command", side_effect=write_command
        ), patch("app.engine.read_host_command_result", side_effect=read_result):
            save_server_state(timeout=0.5, cb=messages.append)

        self.assertEqual(sent["action"], "save_all")
        self.assertTrue(sent["requestId"])
        self.assertIn("Save confirmed for 3 connected characters", messages[-1])

    def test_client_launch_uses_native_profile_without_command_line_overrides(self) -> None:
        install = MorrowindInstall(
            root=Path("F:/SteamLibrary/steamapps/common/Morrowind"),
            data_files=Path("F:/SteamLibrary/steamapps/common/Morrowind/Data Files"),
            source="steam",
        )
        engine = Path("C:/MorrowFriends/tes3mp/0.8.1")

        command = _client_launch_command(engine / "tes3mp.exe", engine, install, VANILLA)

        self.assertEqual(command, [str(engine / "tes3mp.exe")])

    def test_missing_native_profile_is_prepared_without_wizard(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            install = MorrowindInstall(
                root=root / "Morrowind",
                data_files=root / "Morrowind" / "Data Files",
                source="steam",
            )
            profile_dir = root / "Documents" / "My Games" / "OpenMW"

            path = ensure_native_openmw_profile(
                install, VANILLA, directory=profile_dir
            )
            profile = path.read_text(encoding="utf-8")

            self.assertIn(f'data="{install.data_files.as_posix()}"', profile)
            self.assertIn("fallback-archive=Morrowind.bsa", profile)
            self.assertIn("content=Morrowind.esm", profile)
            self.assertIn("content=Tribunal.esm", profile)
            self.assertIn("content=Bloodmoon.esm", profile)

    def test_compatible_native_profile_is_preserved_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            install = MorrowindInstall(
                root=root / "Morrowind",
                data_files=root / "Morrowind" / "Data Files",
                source="steam",
            )
            profile_dir = root / "OpenMW"
            profile_dir.mkdir()
            original = (
                f'data="{install.data_files.as_posix()}"\n'
                "fallback-archive=Morrowind.bsa\n"
                "fallback-archive=Tribunal.bsa\n"
                "fallback-archive=Bloodmoon.bsa\n"
                "content=Morrowind.esm\n"
                "content=Tribunal.esm\n"
                "content=Bloodmoon.esm\n"
            )
            path = profile_dir / "openmw.cfg"
            path.write_text(original, encoding="utf-8")

            ensure_native_openmw_profile(install, VANILLA, directory=profile_dir)

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_vc_runtime_check_requires_all_tes3mp_imports(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            system_root = root / "Windows"
            system32 = system_root / "System32"
            engine_root = root / "engine"
            system32.mkdir(parents=True)
            engine_root.mkdir()

            self.assertFalse(
                vc_runtime_ready(system_root=system_root, engine_root=engine_root)
            )
            for dll in VC_RUNTIME_DLLS:
                (system32 / dll).touch()
            self.assertTrue(
                vc_runtime_ready(system_root=system_root, engine_root=engine_root)
            )

    def test_vc_runtime_installer_uses_verified_official_download(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            downloads = Path(raw)
            messages: list[str] = []

            def retrieve(url, destination, reporthook):
                self.assertEqual(url, VC_RUNTIME_DOWNLOAD_URL)
                Path(destination).write_bytes(b"signed installer")
                reporthook(1, 1, 1)

            with patch("app.engine.downloads_dir", return_value=downloads), patch(
                "app.engine.vc_runtime_ready", side_effect=[False, True]
            ), patch("app.engine.urlretrieve", side_effect=retrieve), patch(
                "app.engine._valid_microsoft_signature", return_value=True
            ), patch("app.engine.subprocess.run") as run:
                run.return_value.returncode = 0
                restart_required = install_vc_runtime(messages.append)

            self.assertFalse(restart_required)
            installer_command = run.call_args.args[0]
            self.assertEqual(Path(installer_command[0]).name, "vc_redist.x64.exe")
            self.assertEqual(installer_command[1:], ["/install", "/passive", "/norestart"])
            self.assertIn("Download verified", messages[-2])
            self.assertIn("installed and verified", messages[-1])

    @patch("app.engine.download_tes3mp")
    def test_repair_forces_a_fresh_verified_download(self, download_tes3mp) -> None:
        installed = Path("C:/fake/tes3mp")
        download_tes3mp.return_value = installed
        messages: list[str] = []

        result = repair_tes3mp(messages.append)

        self.assertEqual(result, installed)
        download_tes3mp.assert_called_once_with(messages.append, force=True)
        self.assertIn("fresh verified download", messages[0])
        self.assertIn("repair complete", messages[-1])

    def test_ready_requires_support_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "tes3mp.exe").touch()
            (root / "tes3mp-server.exe").touch()
            self.assertIsNone(tes3mp_ready(root))
            for relative in REQUIRED_TES3MP_PATHS:
                path = root / relative
                if Path(relative).suffix:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                else:
                    path.mkdir(parents=True, exist_ok=True)
            self.assertEqual(tes3mp_ready(root), root)

    def test_zip_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            good = root / "good.zip"
            with zipfile.ZipFile(good, "w") as archive:
                archive.writestr("TES3MP/tes3mp.exe", b"binary")
            self.assertTrue(_valid_tes3mp_zip(good))
            digest = hashlib.sha256(good.read_bytes()).hexdigest()
            self.assertTrue(_valid_tes3mp_zip(good, digest))
            self.assertFalse(_valid_tes3mp_zip(good, "0" * 64))
            bad = root / "bad.zip"
            bad.write_bytes(b"not a zip")
            self.assertFalse(_valid_tes3mp_zip(bad))

    def test_extract_preserves_server_saves(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dest = root / "install"
            save = dest / "server" / "data" / "world.json"
            save.parent.mkdir(parents=True)
            save.write_text("saved world", encoding="utf-8")
            archive_path = root / "engine.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("TES3MP/tes3mp.exe", b"new binary")
                archive.writestr("TES3MP/server/scripts/serverCore.lua", b"new core")
            _extract_zip(archive_path, dest, None)
            self.assertEqual(save.read_text(encoding="utf-8"), "saved world")
            self.assertTrue((dest / "tes3mp.exe").is_file())


if __name__ == "__main__":
    unittest.main()
