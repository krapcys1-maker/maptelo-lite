"""What a person deletes in Studio: on Windows into the Recycle Bin, where it can be taken
back from as any file deleted in Explorer; elsewhere for good. Only folders Studio made are
ever given here (a process's recordings and maps)."""

from __future__ import annotations

import ctypes
import shutil
import sys
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


def _recycle(paths: list[Path]) -> None:
    """Into the Recycle Bin, without Explorer's own questions (the page asked already)."""
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
    failed = shell.SHFileOperationW(ctypes.byref(operation))
    if failed or operation.fAnyOperationsAborted:
        raise OSError(f"{paths[0].name} could not be deleted (Windows says {failed})")
