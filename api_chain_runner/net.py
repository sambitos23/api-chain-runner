"""Network helpers shared by the CLI and the web UI."""
from __future__ import annotations

import os
import socket
import threading

from urllib3.util import connection as _conn

_local = threading.local()
_orig_create_connection = _conn.create_connection
_orig_allowed_gai_family = _conn.allowed_gai_family
_installed = False


def _allowed_family():
    forced = getattr(_local, "family", None)
    return forced if forced is not None else _orig_allowed_gai_family()


def _create_connection_ipv4_first(address, *args, **kwargs):
    """Connect over IPv4 first, falling back to the normal lookup only if the host has no IPv4 address.

    urllib3 walks the DNS answers in order. On networks that resolve AAAA records but
    cannot route IPv6, every IPv6 address burns the full connect timeout (30 s each)
    before an IPv4 address is tried, so a request can take 90 s or more.
    """
    _local.family = socket.AF_INET
    try:
        return _orig_create_connection(address, *args, **kwargs)
    except socket.gaierror:
        pass  # no A record: let the default resolution try IPv6
    finally:
        _local.family = None
    return _orig_create_connection(address, *args, **kwargs)


def prefer_ipv4() -> None:
    """Install the IPv4-first connector (idempotent). Set API_CHAIN_RUNNER_IPV6_FIRST=1 to skip it."""
    global _installed
    if _installed or os.environ.get("API_CHAIN_RUNNER_IPV6_FIRST"):
        return
    _conn.allowed_gai_family = _allowed_family
    _conn.create_connection = _create_connection_ipv4_first
    _installed = True
