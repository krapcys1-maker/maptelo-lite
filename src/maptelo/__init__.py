"""Maptelo: map business processes from demonstrations and run them with verified results."""

from importlib.metadata import PackageNotFoundError, version


def _version() -> str:
    for name in ("maptelo", "maptelo-lite"):  # the full Maptelo, or Maptelo Lite's package
        try:
            return version(name)
        except PackageNotFoundError:
            continue
    return "0.0.0+unknown"  # running from a source tree without installation


__version__ = _version()
