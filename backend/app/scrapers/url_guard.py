"""URL validation and SSRF protection.

Competitor URLs are user-supplied, so every one is validated before a request
leaves the process:

* only ``http`` and ``https`` schemes,
* no credentials embedded in the URL,
* the resolved IP must not be private, loopback, link-local or reserved,
* redirects are re-validated hop by hop (see the fetcher).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

from app.config.logging import get_logger
from app.config.settings import settings

logger = get_logger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that always point somewhere internal.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
    }
)
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched."""


class UnresolvableHostError(UnsafeURLError):
    """Raised when a hostname does not resolve.

    A subclass of :class:`UnsafeURLError` so strict callers still fail closed,
    but distinguishable so the fetcher can report "host not found" rather than
    the misleading "unsafe URL".
    """


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address that is not a normal public destination."""
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def normalize_url(raw_url: str) -> str:
    """Strip fragments and whitespace, defaulting to https when no scheme."""
    url = (raw_url or "").strip()
    if not url:
        raise UnsafeURLError("empty URL")
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def validate_url(
    raw_url: str, *, allow_private: bool | None = None, strict_dns: bool = True
) -> str:
    """Validate a URL for fetching and return its normalised form.

    Raises :class:`UnsafeURLError` when the URL must not be requested.

    ``strict_dns`` controls what happens when a hostname cannot be resolved.
    The fetcher keeps it ``True`` (fail closed).  The API input layer passes
    ``False`` so a competitor is not rejected merely because DNS is down or the
    domain has not propagated yet — an unresolvable host is not an SSRF target,
    and the fetch path re-validates strictly before any request is made.
    """
    allow_private = settings.allow_private_networks if allow_private is None else allow_private
    url = normalize_url(raw_url)
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"unsupported scheme {parsed.scheme!r} (only http/https allowed)")
    if parsed.username or parsed.password:
        raise UnsafeURLError("credentials embedded in URL are not allowed")

    hostname = (parsed.hostname or "").casefold()
    if not hostname:
        raise UnsafeURLError("URL has no hostname")

    if allow_private:
        return url

    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"hostname {hostname!r} resolves to a private network")

    # A literal IP can be checked without DNS.
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise UnsafeURLError(f"IP {hostname} is in a private or reserved range")
        return url

    # Otherwise resolve and check every address the name maps to.
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        if strict_dns:
            raise UnresolvableHostError(f"cannot resolve hostname {hostname!r}") from exc
        logger.debug("Could not resolve %s during validation; deferring to fetch time", hostname)
        return url

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise UnsafeURLError(f"{hostname} resolves to private address {address}")

    return url


def is_safe_url(
    raw_url: str, *, allow_private: bool | None = None, strict_dns: bool = True
) -> bool:
    """Boolean form of :func:`validate_url`."""
    try:
        validate_url(raw_url, allow_private=allow_private, strict_dns=strict_dns)
        return True
    except UnsafeURLError:
        return False


def same_origin(url_a: str, url_b: str) -> bool:
    """True when two URLs share scheme, host and port."""
    a, b = urlparse(url_a), urlparse(url_b)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


def guess_page_type(url: str) -> str:
    """Infer what kind of page a URL points at, for location hinting."""
    path = urlparse(url).path.casefold()
    rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("pricing", ("pricing", "price", "plans", "billing")),
        ("careers", ("career", "jobs", "hiring", "join-us", "work-with-us")),
        ("blog", ("blog", "news", "press", "changelog", "release", "announcement")),
        ("integrations", ("integration", "partners", "marketplace", "connectors")),
        ("product", ("product", "features", "platform", "solutions")),
    )
    for page_type, needles in rules:
        if any(needle in path for needle in needles):
            return page_type
    return "generic"
