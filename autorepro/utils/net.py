"""Target-URL vetting for server-side fetches (SSRF guard)."""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests

from utils import config


class BlockedTargetError(Exception):
    """Raised when a target URL resolves to an address we refuse to fetch."""


# Names Docker maps to the host gateway. They resolve on the host that runs the sandbox,
# not here, and they always point at the host itself — so they count as private.
_DOCKER_HOST_ALIASES = ("host.docker.internal", "gateway.docker.internal")
_AWS_IMDS_V6 = ipaddress.ip_address("fd00:ec2::254")
MAX_REDIRECTS = 5


def _normalise(address: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    """Unwrap IPv4-mapped IPv6 (::ffff:a.b.c.d) to the IPv4 address it really is.

    Without this, ``http://[::ffff:169.254.169.254]/`` sailed past every IPv4 check.
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to every address it answers with; [] if it doesn't resolve.

    An unresolvable name has nothing to vet: the fetch fails on its own with a clear
    network error, which is the fail-soft behaviour the rest of the pipeline relies on.
    """
    try:
        return [_normalise(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return []
    return [_normalise(ipaddress.ip_address(info[4][0].split("%", 1)[0])) for info in infos]


def _is_metadata(address: ipaddress._BaseAddress) -> bool:
    """Link-local space holds every major cloud's instance metadata service."""
    return address.is_link_local or address == _AWS_IMDS_V6


def _is_internal(address: ipaddress._BaseAddress) -> bool:
    return (address.is_private or address.is_loopback or address.is_reserved
            or address.is_unspecified or address.is_multicast)


def check_target(url: str) -> None:
    """Raise BlockedTargetError if ``url`` must not be fetched from the API host.

    DNS is resolved first, so a public name pointing at an internal address is caught.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedTargetError(f"Unsupported scheme: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise BlockedTargetError("Target URL has no host")

    if host.lower() in _DOCKER_HOST_ALIASES:
        if config.ALLOW_PRIVATE_TARGETS:
            return
        raise BlockedTargetError(
            f"{host} points at the Docker host; set ALLOW_PRIVATE_TARGETS=true to allow it")

    # ponytail: resolve-then-fetch leaves a DNS-rebinding window; pin the resolved IP
    # in the connection if targets ever come from untrusted users at scale.
    for address in _resolve(host):
        if _is_metadata(address):
            raise BlockedTargetError(
                f"{host} resolves to {address}, which is a link-local/metadata address")
        if not config.ALLOW_PRIVATE_TARGETS and _is_internal(address):
            raise BlockedTargetError(
                f"{host} resolves to the private address {address}; set "
                "ALLOW_PRIVATE_TARGETS=true to allow internal targets")


def guarded_get(url: str, **kwargs) -> requests.Response:
    """GET ``url``, re-vetting every redirect hop against the SSRF guard.

    requests follows redirects by default, so a public page answering
    ``302 Location: http://169.254.169.254/`` used to walk straight past check_target.
    """
    kwargs["allow_redirects"] = False
    for _ in range(MAX_REDIRECTS + 1):
        response = requests.get(url, **kwargs)
        location = response.headers.get("Location") if response.is_redirect is True else None
        if not isinstance(location, str) or not location:
            return response
        url = urljoin(url, location)
        check_target(url)
    raise BlockedTargetError(f"More than {MAX_REDIRECTS} redirects")
