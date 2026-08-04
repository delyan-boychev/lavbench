"""Client IP resolution behind the nginx reverse proxy.

nginx sets both ``X-Real-IP`` and ``X-Forwarded-For`` from ``$remote_addr`` at
the edge (see frontend/nginx.conf), so a client cannot spoof them by sending
its own headers. We key rate limiting and audit logging on these values.
"""

from __future__ import annotations

from flask import request


def get_client_ip() -> str:
    """Return the true peer IP of the proxied client.

    Prefers ``X-Real-IP`` (set by nginx from the direct TCP peer), then falls
    back to ``request.remote_addr``. Under ``ProxyFix(x_for=1)`` the latter is
    the nginx-overwritten ``X-Forwarded-For`` first entry when reachable via
    the proxy, and the raw socket peer when reached directly (dev mode) — so
    neither path is user-spoofable.
    """
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"
