"""The bridge's helper Python runs the Maptelo that started it, not one installed in that Python
(a worktree measured with the main checkout's environment ran the main checkout's bridge)."""

from __future__ import annotations

import subprocess
import sys

from maptelo.desktop.jab_remote import BOOT, ROOT


def test_the_helper_imports_maptelo_from_the_folder_it_was_given() -> None:
    probe = BOOT.replace(
        "from maptelo.desktop.jab_remote import serve; serve()",
        "import maptelo; print(maptelo.__file__)",
    )
    assert probe != BOOT
    out = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(ROOT)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out.lower().startswith(str(ROOT).lower())
