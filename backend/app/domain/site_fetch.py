"""Host rules for a project site and for cited URLs.

Nothing here performs I/O. `canonical_host` and `same_site_host` compare one
spelling of a site, including its subdomains. `is_public_address` refuses a
literal that is not a public IP, so a citation cannot point at a private host.
"""

from __future__ import annotations

import ipaddress

from app.core.errors import ValidationError
from app.domain.search import INVALID_SITE, normalize_search_host

LOCAL_NAMES = frozenset({"localhost", "local", "localdomain"})
LOCAL_NAME_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".home.arpa")


def canonical_host(value: object) -> str:
    """Return the canonical host of a URL or bare host, or raise ValidationError.

    The result is lowercase ASCII: the trailing dot and a leading `www.` are
    dropped, so every rule built on it compares one spelling of a site.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(INVALID_SITE)
    host = normalize_search_host(value.strip())
    canonical = host.removeprefix("www.")
    if "." not in canonical:
        raise ValidationError(INVALID_SITE)
    return canonical


def same_site_host(target: str, candidate: str) -> bool:
    """Report whether two names are the same host or the candidate is a subdomain.

    A lookalike such as `example.ru.attacker.test` never matches `example.ru`, and
    a dropped leading `www.` never hides the difference.
    """
    host = _bare_host(target)
    other = _bare_host(candidate)
    if not host or not other:
        return False
    return other == host or other.endswith(f".{host}")


def is_public_address(value: str) -> bool:
    """Report whether a value is a public IP literal.

    Loopback, private, link-local, multicast, reserved, unspecified, site-local,
    shared, and local names are refused; anything that is not an IP literal is
    refused as well, because a name is not an address that was checked.
    """
    if not isinstance(value, str):
        return False
    host = value.strip().strip("[]").rstrip(".").lower()
    if not host or host in LOCAL_NAMES or host.endswith(LOCAL_NAME_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return False
    return address.is_global


def _bare_host(value: str) -> str:
    """Lowercase a host name, dropping its trailing dot and a leading `www.`."""
    if not isinstance(value, str):
        return ""
    host = value.strip().rstrip(".").lower()
    return host.removeprefix("www.")
