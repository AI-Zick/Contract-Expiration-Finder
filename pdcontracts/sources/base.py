"""Connector interface and the shared HTTP layer.

All network access goes through HttpFetcher so tests can substitute recorded
responses and the whole suite runs offline.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..models import Contract

DEFAULT_TIMEOUT = 45
USER_AGENT = "pdcontracts/0.1 (public procurement research)"


class FetchError(RuntimeError):
    pass


class HttpFetcher:
    """Thin requests wrapper with retry and polite rate limiting."""

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = 3,
        delay: float = 0.4,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if headers:
            self.headers.update(headers)
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests  # imported lazily so the package works without network deps

            self._session = requests.Session()
        return self._session

    def get_json(self, url: str, params: Optional[dict] = None,
                 headers: Optional[dict] = None):
        raw = self.get_text(url, params=params, headers=headers)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise FetchError(f"{url} did not return JSON: {raw[:200]}") from exc

    def get_text(self, url: str, params: Optional[dict] = None,
                 headers: Optional[dict] = None) -> str:
        session = self._get_session()
        merged = dict(self.headers)
        if headers:
            merged.update(headers)
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                response = session.get(
                    url, params=params, headers=merged, timeout=self.timeout
                )
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                time.sleep(self.delay)
                return response.text
            except Exception as exc:  # noqa: BLE001 - retried and reported
                last = exc
                # No backoff after the final attempt -- there is nothing left
                # to wait for, and across a sweep of hundreds of probes that
                # dead time dominates the run.
                if attempt < self.retries - 1:
                    time.sleep(min(2 ** attempt, 8))
        raise FetchError(f"GET {url} failed after {self.retries} attempts: {last}")

    def post_json(self, url: str, payload: dict, headers: Optional[dict] = None):
        session = self._get_session()
        merged = dict(self.headers)
        merged["Content-Type"] = "application/json"
        if headers:
            merged.update(headers)
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                response = session.post(
                    url, json=payload, headers=merged, timeout=self.timeout
                )
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                time.sleep(self.delay)
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < self.retries - 1:
                    time.sleep(min(2 ** attempt, 8))
        raise FetchError(f"POST {url} failed after {self.retries} attempts: {last}")


@dataclass
class SourceResult:
    contracts: List[Contract] = field(default_factory=list)
    fetched: int = 0
    status: str = "ok"
    message: str = ""
    dataset: str = ""


class Source:
    """Base connector.

    Subclasses implement ``collect`` and return a SourceResult. They should
    never raise for ordinary data problems -- return status='error' with a
    message so one broken portal does not abort a national collection run.
    """

    id = "base"
    label = "Base source"
    # How much to trust numbers from this source before classification.
    default_confidence = 0.5

    def __init__(self, config: Optional[dict] = None, fetcher: Optional[HttpFetcher] = None):
        self.config = config or {}
        self.fetcher = fetcher or HttpFetcher()

    def collect(self, **kwargs) -> SourceResult:
        raise NotImplementedError

    def check(self) -> SourceResult:
        """Lightweight reachability probe used by ``pdcontracts doctor``."""
        raise NotImplementedError


registry: Dict[str, type] = {}


def register(cls):
    registry[cls.id] = cls
    return cls
