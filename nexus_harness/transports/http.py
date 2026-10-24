"""JSON over `urllib`, and a failure that says what happened.

Every transport needs the same four things: a UA header some gateways require, a timeout, a retry on
the two statuses that mean "not now" (429, 5xx), and an error that carries the status and the body so
the caller can print something a human can act on. Standard library only: `urllib.request`.
"""
import json
import time
import urllib.error
import urllib.request

USER_AGENT = "NexusHarness/0.1 (+local)"
RETRY_STATUS = (429, 500, 502, 503, 504)


class TransportError(RuntimeError):
    """A call that did not produce JSON, with the evidence that says why."""

    def __init__(self, message, status=None, body=""):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def retryable(self):
        return self.status in RETRY_STATUS


def _request(url, payload=None, headers=None, timeout=120, method=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("User-Agent", USER_AGENT)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1500]
        raise TransportError("%s -> HTTP %s: %s" % (url, exc.code, body[:400]),
                             status=exc.code, body=body) from exc
    except urllib.error.URLError as exc:
        raise TransportError("%s unreachable: %s" % (url, exc.reason)) from exc
    except TimeoutError as exc:
        raise TransportError("%s timed out after %ss" % (url, timeout)) from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        raise TransportError("%s returned non-JSON: %r" % (url, raw[:200])) from exc


def post_json(url, payload, headers=None, timeout=120, retries=1):
    """POST JSON, retrying once on the statuses that mean the server is busy, not wrong."""
    attempt = 0
    while True:
        try:
            return _request(url, payload, headers, timeout)
        except TransportError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            attempt += 1
            time.sleep(min(2 ** attempt, 8))


def get_json(url, headers=None, timeout=30, retries=1):
    attempt = 0
    while True:
        try:
            return _request(url, None, headers, timeout)
        except TransportError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            attempt += 1
            time.sleep(min(2 ** attempt, 8))
