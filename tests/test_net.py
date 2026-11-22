"""IPv4-first connection ordering (avoids long stalls when IPv6 is unroutable)."""
from __future__ import annotations

import socket

import pytest
from urllib3.util import connection

from api_chain_runner import net


@pytest.fixture
def listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    yield srv
    srv.close()


def test_executor_installs_the_ipv4_first_connector():
    import api_chain_runner.executor  # noqa: F401

    assert connection.create_connection is net._create_connection_ipv4_first


def test_ipv4_is_resolved_first_and_ipv6_never_waited_on(listener, monkeypatch):
    port = listener.getsockname()[1]
    families = []

    def fake_getaddrinfo(host, p, family=0, type=0, *a, **k):
        families.append(family)
        v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
        v6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", port, 0, 0))  # unroutable
        return [v4] if family == socket.AF_INET else [v6, v4]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    sock = net._create_connection_ipv4_first(("example.test", port), timeout=2)
    sock.close()
    assert families == [socket.AF_INET]


def test_falls_back_to_default_resolution_when_host_has_no_ipv4(monkeypatch):
    families = []

    def fake_getaddrinfo(host, p, family=0, type=0, *a, **k):
        families.append(family)
        if family == socket.AF_INET:
            raise socket.gaierror(socket.EAI_NONAME, "no A record")
        raise OSError("stop here")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(OSError):
        net._create_connection_ipv4_first(("v6only.test", 443), timeout=1)
    assert families[0] == socket.AF_INET and len(families) == 2 and families[1] != socket.AF_INET
    assert getattr(net._local, "family", None) is None  # override never leaks to other requests
