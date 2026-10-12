"""MiniERP: a small, deliberately unreliable pricing application (Maptelo's test bench)."""

from minierp.app import create_app
from minierp.config import CHAOS_PRESETS, Chaos, Settings

__all__ = ["CHAOS_PRESETS", "Chaos", "Settings", "create_app"]
