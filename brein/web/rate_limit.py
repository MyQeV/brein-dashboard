"""Rate limiter for auth and sensitive endpoints (login, setup, user creation)."""

import ipaddress

from brein import config as brein_config
from slowapi import Limiter
from starlette.requests import Request


def is_trusted_proxy(request: Request) -> bool:
    """Whether the immediate peer is one of the configured trusted proxies.

    Anything a proxy asserts in an X-Forwarded-* header — the client IP, the
    host — is only worth reading when the peer sending it is trusted.
    """
    peer = request.client.host if request.client else ""
    if not brein_config.TRUSTED_PROXIES or not peer:
        return False
    return _in_trusted_network(peer)


def _in_trusted_network(addr: str) -> bool:
    try:
        parsed = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for entry in brein_config.TRUSTED_PROXIES:
        try:
            if parsed in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue  # skip malformed CIDR entries
    return False


def get_client_ip(request: Request) -> str:
    """Return the real client IP, respecting X-Forwarded-For from trusted proxies.

    X-Forwarded-For is a list the client starts and each proxy appends to, so
    the *leftmost* entry is whatever the client typed. Reading it — as this
    did — handed every caller a rate-limit bucket of their own choosing: a
    login attempt with an incremented `X-Forwarded-For` per request never hits
    the ten-per-minute limit, which is unlimited password guessing. Only the
    entries a trusted proxy appended are worth anything, so the list is walked
    from the right and the first hop that is not itself a trusted proxy wins.

    This is only as good as TRUSTED_PROXIES, which must therefore name the
    proxies actually in front of this app and nothing else — a proxy that does
    not append its own view of the peer (Next's rewrite proxy does not) gives
    the header no trustworthy content at all, which is why the shipped default
    is now empty.
    """
    peer = request.client.host if request.client else ""

    if not brein_config.TRUSTED_PROXIES:
        return peer  # fast path: no proxy trust configured

    if not _in_trusted_network(peer):
        return peer  # the peer is not a proxy; its own address is the client

    forwarded = [
        part.strip()
        for part in request.headers.get("X-Forwarded-For", "").split(",")
        if part.strip()
    ]
    for candidate in reversed(forwarded):
        if not _in_trusted_network(candidate):
            return candidate

    # Every hop was a trusted proxy, or the header was absent. X-Real-IP is a
    # single value a proxy sets itself, so it is usable here for the same
    # reason and no more.
    real_ip = request.headers.get("X-Real-IP", "").strip()
    return real_ip or peer


limiter = Limiter(key_func=get_client_ip)
