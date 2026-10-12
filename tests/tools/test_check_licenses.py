from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "check_licenses.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_licenses", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("expression", "verdict"),
    [
        ("MIT", "allowed"),
        ("BSD-3-Clause", "allowed"),
        ("Apache-2.0 OR BSD-2-Clause", "allowed"),
        ("MIT AND PSF-2.0", "allowed"),
        ("Apache-2.0 WITH LLVM-exception", "allowed"),
        ("MPL-2.0", "dependency only"),
        ("LGPL-3.0-or-later", "dependency only"),
        ("GPL-3.0-only", "denied"),
        ("AGPL-3.0", "denied"),
        ("SSPL-1.0", "denied"),
        ("GPL-2.0-only OR MIT", "allowed"),
        ("MIT AND GPL-3.0-only", "denied"),
        ("LicenseRef-Proprietary", "unknown"),
    ],
)
def test_classify_expression(checker: ModuleType, expression: str, verdict: str) -> None:
    assert checker.classify_expression(expression) == verdict


def test_sniffs_full_license_texts(checker: ModuleType) -> None:
    assert checker.sniff_text("Permission is hereby granted, free of charge, to any") == "MIT"
    assert checker.sniff_text("Apache License\nVersion 2.0, January 2004") == "Apache-2.0"
    assert checker.sniff_text("GNU AFFERO GENERAL PUBLIC LICENSE") == "AGPL-3.0"
    assert checker.sniff_text("All rights reserved.") is None


def test_exceptions_file_format(checker: ModuleType, tmp_path: Path) -> None:
    listed = tmp_path / "exceptions.txt"
    listed.write_text("# comment\nSome_Package  # MIT, checked by hand\n\n", encoding="utf-8")
    assert checker.load_exceptions(listed) == {"some-package": "MIT, checked by hand"}
