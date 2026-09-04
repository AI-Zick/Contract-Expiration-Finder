import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


class FakeFetcher:
    """Stands in for HttpFetcher so connector tests run without network.

    Responses are keyed by a substring of the URL; the first match wins.
    """

    def __init__(self, responses=None, pages=None):
        self.responses = responses or {}
        # pages: url-substring -> list of successive payloads, popped in order
        self.pages = pages or {}
        self.calls = []

    def _lookup(self, url, params=None):
        self.calls.append((url, params))
        for key, queue in self.pages.items():
            if key in url:
                return queue.pop(0) if queue else []
        for key, value in self.responses.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected request: {url} {params}")

    def get_json(self, url, params=None, headers=None):
        return self._lookup(url, params)

    def post_json(self, url, payload, headers=None):
        self.calls.append((url, payload))
        for key, value in self.responses.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected POST: {url}")

    def get_text(self, url, params=None, headers=None):
        import json

        return json.dumps(self._lookup(url, params))


@pytest.fixture
def fake_fetcher():
    return FakeFetcher
