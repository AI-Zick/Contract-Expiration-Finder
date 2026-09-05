"""Data source connectors."""

from .base import Source, SourceResult, HttpFetcher, registry, register  # noqa: F401
from . import socrata, usaspending, csvfile, cooperative, legistar  # noqa: F401,E402
