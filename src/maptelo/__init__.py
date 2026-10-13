"""Maptelo: map business processes from demonstrations and run them with verified results."""

from importlib.metadata import PackageNotFoundError, version


def _installed() -> tuple[str, str]:
    """The product's name and version: the full Maptelo, or Maptelo Lite's package."""
    for name, product in (("maptelo", "Maptelo"), ("maptelo-lite", "Maptelo Lite")):
        try:
            return product, version(name)
        except PackageNotFoundError:
            continue
    return "Maptelo", "0.0.0+unknown"  # running from a source tree without installation


PRODUCT, __version__ = _installed()
