"""Guard against reading a `self.X` that nothing ever assigns.

This bug class has bitten three times in this file:

1. 2026-08-18 the host cockpit was deleted. Its widget CREATION went; every use
   site stayed. `_play_now` -> `_require_vc_runtime` -> `vc_runtime_status_var`
   raised AttributeError, and because a windowed PyInstaller build discards
   stderr, the Play button looked simply dead.
2. Same removal orphaned `repair_engine_btn` / `engine_repair_status_var`, so
   "Repair TES3MP" — one of the two escape hatches the README promises — was
   dead at the same time.
3. 2026-08-20, moving the pack menu into the Settings window orphaned
   `pack_menu`, which `_play_now` reads on EVERY launch via
   `_selected_pack_id()`. That would have shipped a dead Play button again, in
   the very session that fixed the first one.

Tk swallows exceptions raised inside widget callbacks, so none of these fail
loudly at runtime. A static check is the only cheap way to catch them.

An attribute is considered SAFE if it is assigned somewhere in the class, or if
every read is defensive (`getattr(self, "x", ...)` / `hasattr(self, "x")`).
"""

from __future__ import annotations

import ast
import pathlib
import unittest

MAIN = pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py"


def _app_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            return node
    raise AssertionError("class App not found in app/main.py")


class OrphanWidgetTests(unittest.TestCase):
    def test_every_self_attribute_read_is_assigned_or_guarded(self) -> None:
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        app = _app_class(tree)

        assigned: set[str] = set()
        read: dict[str, int] = {}
        guarded: set[str] = set()

        for node in ast.walk(app):
            # self.x = ..., self.x: T = ..., for self.x in ..., with ... as self.x
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            elif isinstance(node, ast.For):
                targets = [node.target]
            for tgt in targets:
                for sub in ast.walk(tgt):
                    if (
                        isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"
                    ):
                        assigned.add(sub.attr)

            # getattr(self, "x", ...) / hasattr(self, "x") are defensive reads
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"getattr", "hasattr", "setattr"} and len(node.args) >= 2:
                    first, second = node.args[0], node.args[1]
                    if (
                        isinstance(first, ast.Name)
                        and first.id == "self"
                        and isinstance(second, ast.Constant)
                        and isinstance(second.value, str)
                    ):
                        guarded.add(second.value)
                        if node.func.id == "setattr":
                            assigned.add(second.value)

        for node in ast.walk(app):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and isinstance(node.ctx, ast.Load)
            ):
                read.setdefault(node.attr, node.lineno)

        # Anything defined on the class or inherited from CTk is fine.
        import customtkinter as ctk

        inherited = set(dir(ctk.CTk))
        class_level = {
            n.name for n in app.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        orphans = {
            name: line
            for name, line in read.items()
            if name not in assigned
            and name not in guarded
            and name not in class_level
            and name not in inherited
            and not name.startswith("__")
        }

        self.assertEqual(
            orphans,
            {},
            "app/main.py reads self.<attr> that nothing assigns — this is the "
            "dead-Play-button bug. Assign it, or read it via "
            "getattr(self, name, None):\n"
            + "\n".join(f"  self.{n}  (first read at main.py:{ln})" for n, ln in sorted(orphans.items())),
        )


if __name__ == "__main__":
    unittest.main()
