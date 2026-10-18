"""What a person deletes in Studio: on Windows into the Recycle Bin, where it can be taken
back from as any file deleted in Explorer; elsewhere for good. Only folders Studio made are
ever given here (a process's recordings and maps)."""

from __future__ import annotations

import ctypes
import shutil
import sys
import time
from pathlib import Path


def discard(paths: list[Path]) -> None:
    present = [path for path in paths if path.exists()]
    if not present:
        return
    if sys.platform == "win32":
        _recycle(present)
        return
    for path in present:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


class _FileOperation(ctypes.Structure):
    """SHFILEOPSTRUCTW, as a 64-bit Windows lays it out."""

    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
IN_USE = frozenset({32, 33, 124, 1224})
"""What Windows says of a file another program holds: shared (32), locked (33), mapped into
memory (1224, as an antivirus or Explorer's preview reads a picture), or, from the Recycle Bin's
old codes, a file it could not move (124, a file left open)."""
TRIES = 5
"""A file is often held only while it is read (a scan of the new screenshots): asked again."""
PAUSE_S = 0.5


def _recycle(paths: list[Path]) -> None:
    """Into the Recycle Bin, without Explorer's own questions (the page asked already)."""
    failed = 0
    for attempt in range(TRIES):
        present = [path for path in paths if path.exists()]  # some may be in the bin already
        if not present:
            return
        failed, aborted = _shell_delete(present)
        if not failed and not aborted:
            return
        if failed not in IN_USE:
            raise OSError(f"{paths[0].name} could not be deleted (Windows says {failed})")
        if attempt + 1 < TRIES:
            time.sleep(PAUSE_S)
    raise OSError(
        f"{paths[0].name} is still in use (Windows says {failed}); "
        "close its preview or the program using its files and try again"
    )


def _shell_delete(paths: list[Path]) -> tuple[int, bool]:
    """What Windows said of moving these into the Recycle Bin, and whether it stopped short."""
    names = "".join(f"{path.resolve()}\0" for path in paths) + "\0"
    operation = _FileOperation(
        None,
        FO_DELETE,
        names,
        None,
        FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI,
        0,
        None,
        None,
    )
    shell = getattr(ctypes, "windll").shell32  # noqa: B009 (Windows only)
    recycle = shell.SHFileOperationW
    recycle.argtypes = [ctypes.POINTER(_FileOperation)]
    recycle.restype = ctypes.c_int
    failed = recycle(ctypes.byref(operation))
    return failed, bool(operation.fAnyOperationsAborted)
