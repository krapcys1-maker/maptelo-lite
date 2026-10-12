"""Check the licenses of installed dependencies against the project policy.

Policy (docs/02-open-source.md): permissive licenses are fine; weak copyleft (MPL, LGPL,
EPL) only as unmodified dependencies; strong copyleft and non-free licenses are rejected.
An unrecognised license fails too, until someone reviews it and lists the package in
license-exceptions.txt with a reason.

Usage: uv run python tools/check_licenses.py
"""

from __future__ import annotations

import re
import sys
from enum import StrEnum
from importlib import metadata
from pathlib import Path

OWN_PACKAGES = {"maptelo", "maptelo-lite", "minierp"}
EXCEPTIONS_FILE = Path(__file__).with_name("license-exceptions.txt")

PERMISSIVE = {
    "MIT", "MIT-0", "BSD", "0BSD", "Apache-2.0", "ISC", "PSF-2.0", "Python-2.0", "Zlib",
    "Unlicense", "CC0-1.0", "BSL-1.0", "HPND", "UPL-1.0", "MIT-CMU",
}  # fmt: skip
DEPENDENCY_ONLY_PREFIXES = ("MPL", "LGPL", "EPL")
DENIED_PREFIXES = ("GPL", "AGPL", "SSPL", "BUSL", "Elastic", "CC-BY-NC", "Commons-Clause", "EUPL")

CLASSIFIERS = {
    "MIT License": "MIT",
    "MIT No Attribution License (MIT-0)": "MIT-0",
    "BSD License": "BSD",
    "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "The Unlicense (Unlicense)": "Unlicense",
    "Historical Permission Notice and Disclaimer (HPND)": "HPND",
    "zlib/libpng License": "Zlib",
    "Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "GNU General Public License (GPL)": "GPL",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0",
    "GNU Affero General Public License v3": "AGPL-3.0",
}

ALIASES = {
    "mit": "MIT",
    "mit license": "MIT",
    "the mit license": "MIT",
    "bsd": "BSD",
    "bsd license": "BSD",
    "new bsd": "BSD",
    "new bsd license": "BSD",
    "3-clause bsd license": "BSD",
    "bsd 3-clause": "BSD",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "psf": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "isc": "ISC",
    "mpl 2.0": "MPL-2.0",
}


class Verdict(StrEnum):
    ALLOWED = "allowed"
    DEPENDENCY_ONLY = "dependency only"
    UNKNOWN = "unknown"
    DENIED = "denied"


_RANK = {Verdict.ALLOWED: 0, Verdict.DEPENDENCY_ONLY: 1, Verdict.UNKNOWN: 2, Verdict.DENIED: 3}


def classify_id(license_id: str) -> Verdict:
    lid = license_id.strip().split(" WITH ")[0].strip().removesuffix("+")
    if lid in PERMISSIVE or lid.startswith("BSD-"):
        return Verdict.ALLOWED
    if lid.startswith(DEPENDENCY_ONLY_PREFIXES):
        return Verdict.DEPENDENCY_ONLY
    if lid.startswith(DENIED_PREFIXES):
        return Verdict.DENIED
    return Verdict.UNKNOWN


def classify_expression(expression: str) -> Verdict:
    """SPDX-style: one acceptable alternative of an OR is enough; every part of an AND counts."""
    flat = expression.replace("(", " ").replace(")", " ").strip()
    verdicts = []
    for alternative in re.split(r"\s+OR\s+", flat, flags=re.IGNORECASE):
        parts = re.split(r"\s+AND\s+", alternative.strip(), flags=re.IGNORECASE)
        verdicts.append(max((classify_id(p) for p in parts), key=_RANK.__getitem__))
    return min(verdicts, key=_RANK.__getitem__)


def sniff_text(text: str) -> str | None:
    lowered = text.lower()
    checks = [
        ("permission is hereby granted, free of charge", "MIT"),
        ("redistribution and use in source and binary forms", "BSD"),
        ("gnu affero general public license", "AGPL-3.0"),
        ("gnu lesser general public license", "LGPL"),
        ("gnu general public license", "GPL"),
        ("mozilla public license", "MPL-2.0"),
        ("python software foundation", "PSF-2.0"),
    ]
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    return next((spdx for needle, spdx in checks if needle in lowered), None)


def detect(dist: metadata.Distribution) -> tuple[str | None, str]:
    """(license expression, where it was found)."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip(), "License-Expression"
    ids = sorted(
        {
            CLASSIFIERS[c.split(" :: ")[-1]]
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::") and c.split(" :: ")[-1] in CLASSIFIERS
        }
    )
    if ids:
        return " OR ".join(ids), "classifier"
    text = (meta.get("License") or "").strip()
    if text:
        if text.lower() in ALIASES:
            return ALIASES[text.lower()], "License"
        if classify_expression(text) is not Verdict.UNKNOWN:
            return text, "License"
        sniffed = sniff_text(text)
        if sniffed:
            return sniffed, "License text"
    for file in dist.files or []:
        if file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING")):
            path = Path(str(dist.locate_file(file)))
            if path.is_file():
                sniffed = sniff_text(path.read_text(encoding="utf-8", errors="replace"))
                if sniffed:
                    return sniffed, f"file {file.name}"
    return None, "not found"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_exceptions(path: Path = EXCEPTIONS_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    reviewed = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        package, _, reason = line.partition("#")
        if package.strip():
            reviewed[canonical(package.strip())] = reason.strip()
    return reviewed


def main() -> int:
    reviewed = load_exceptions()
    seen: set[str] = set()
    failures = []
    for dist in sorted(metadata.distributions(), key=lambda d: canonical(d.metadata["Name"])):
        name = canonical(dist.metadata["Name"])
        if name in seen or name in OWN_PACKAGES:
            continue
        seen.add(name)
        expression, source = detect(dist)
        verdict = classify_expression(expression) if expression else Verdict.UNKNOWN
        note = ""
        if verdict is Verdict.UNKNOWN and name in reviewed:
            verdict, note = Verdict.ALLOWED, f"reviewed: {reviewed[name]}"
        print(f"{verdict:<16} {name:<28} {expression or '-'}  ({note or source})")
        if verdict in (Verdict.UNKNOWN, Verdict.DENIED):
            failures.append(f"{name}: {verdict} ({expression or 'no license metadata'})")
    if failures:
        print("\nLicense policy violations:\n  " + "\n  ".join(failures))
        print("Review them; a package with an acceptable license goes to license-exceptions.txt.")
        return 1
    print(f"\n{len(seen)} dependencies checked, all within the license policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
