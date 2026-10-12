"""Mapping: from recordings to process models."""

from maptelo.mapping.build import MapResult, map_trace
from maptelo.mapping.naming import Lang, slug
from maptelo.mapping.normalize import Act, Attempt, Normalized, normalize

__all__ = ["Act", "Attempt", "Lang", "MapResult", "Normalized", "map_trace", "normalize", "slug"]
