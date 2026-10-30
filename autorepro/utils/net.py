"""Target-URL vetting for server-side fetches (SSRF guard)."""

import ipaddress
import socket
from urllib.parse import urlsplit

from utils import config


class BlockedTargetError(Exception):
    """Raised when a target URL resolves to an address we refuse to fetch."""


# Cloud instance metadata. Never fetchable, whatever ALLOW_PRIVATE_TARGETS says: the
# inspect node renders unknown content into dom.html, which is a read-back path for
# IMDSv1 credentials.
_METADATA_NETS = (
    ipaddress.ip_network("169.254.0.0/16"),     # AWS/GCP/Azure IMDS, link-local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IMDS over IPv6
)


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to every address it answers with."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BlockedTargetError(f"Could not resolve host {host!r}: {e}") from e
    return [ipaddress.ip_address(info[4][0]) for info in infos]


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

    # Resolved on the host that runs the sandbox, not here.
    if host.lower() in ("host.docker.internal", "gateway.docker.internal"):
        return

    for address in _resolve(host):
        if any(address in net for net in _METADATA_NETS):
            raise BlockedTargetError(
                f"{host} resolves to {address}, which is a link-local/metadata address")
        if config.ALLOW_PRIVATE_TARGETS:
            continue
        if address.is_private or address.is_loopback or address.is_reserved:
            raise BlockedTargetError(
                f"{host} resolves to the private address {address}; set "
                "ALLOW_PRIVATE_TARGETS=true to allow internal targets")
