"""一次性浏览器 ticket：argv 不含真实 token，且只能消费一次。"""

from __future__ import annotations

import http.client
from urllib.parse import urlsplit

import pytest

from weblauncher.tickets import TicketServer


def _get(url: str) -> tuple[int, str | None]:
    parsed = urlsplit(url)
    assert parsed.hostname is not None and parsed.port is not None
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        conn.request("GET", parsed.path)
        response = conn.getresponse()
        response.read()
        return response.status, response.getheader("Location")
    finally:
        conn.close()


def test_ticket_redirects_once_and_hides_target() -> None:
    target = "http://127.0.0.1:1234/lab?token=secret"
    ticket = TicketServer(target)
    ticket.start()
    try:
        assert "secret" not in ticket.url
        assert _get(ticket.url) == (302, target)
        assert _get(ticket.url)[0] == 404
    finally:
        ticket.close()


def test_ticket_rejects_non_http_target() -> None:
    with pytest.raises(ValueError, match="非法跳转目标"):
        TicketServer("javascript:alert(1)")
