"""
Talking to a plugin where it runs: its address checked, its manifest fetched (GET <address>/manifest), its health
asked, and the hosts its address stands for (for "only accept calls from this plugin's address"). A plugin may run
on another machine on the farm's network (http://192.168.10.215:8080) or as a container beside Farmhand
(http://hello:8080). Every problem is in plain words, shown to the operator as it is.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlsplit

import httpx

# Tests swap this for an httpx.MockTransport that plays a plugin (tests/fake_plugin.py)
transport: httpx.BaseTransport | None = None

MANIFEST_TIMEOUT = 8.0
HEALTH_TIMEOUT = 5.0
RESOLVE_FOR = 60.0  # seconds a host's addresses are remembered, for the address check on plugin API calls
_resolved: dict[str, tuple[float, frozenset[str]]] = {}


def check_address(raw) -> str:
    """The plugin's address, tidied (no trailing /); ValueError says what's wrong with it."""
    example = "like http://192.168.10.215:8080"
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Type the plugin's address, {example}.")
    text = raw.strip()
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise ValueError(f"\"{raw.strip()}\" isn't an address Farmhand can use. Type it {example}.") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"The plugin's address must start with http:// or https:// and name a machine, {example}.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"The plugin's address can't have a password, ? or # in it. Type it {example}.")
    if len(text) > 300:
        raise ValueError("The plugin's address is too long (300 characters at most).")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}{f':{port}' if port else ''}{parts.path.rstrip('/')}"


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)


def unreachable(address: str, error: Exception) -> str:
    """Why a plugin couldn't be asked, in plain words."""
    if isinstance(error, httpx.TimeoutException):
        return f"The plugin at {address} didn't answer in time. Is it running, and is the address right?"
    if isinstance(error, httpx.ConnectError):
        return f"Farmhand couldn't reach a plugin at {address} (nothing answered there). Is it running, and is the address right?"
    return f"Farmhand couldn't reach the plugin at {address}: {error}"


def fetch_manifest(address: str) -> dict:
    """The raw manifest the plugin serves at <address>/manifest (checked later); ValueError in plain words."""
    try:
        with _client(MANIFEST_TIMEOUT) as client:
            r = client.get(f"{address}/manifest", headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise ValueError(unreachable(address, e)) from None
    if r.status_code != 200:
        raise ValueError(
            f"Something answered at {address}, but not as a Farmhand plugin: asking it for /manifest got {r.status_code}. "
            "Check the address (and the port)."
        )
    try:
        return r.json()
    except ValueError:
        raise ValueError(
            f"Something answered at {address}, but its /manifest isn't JSON, so it isn't a Farmhand plugin (or not this "
            "version of one). Check the address (and the port)."
        ) from None


def check_health(address: str, path: str | None) -> tuple[str, str | None]:
    """
    (state, why) from asking the plugin's health path (its /manifest if it names none): ("running", None) for a 2xx;
    ("unwell", what it said) when it answers otherwise (it's running, and says what's wrong, e.g. Farmhand refused its
    token); ("not_answering", why) when nothing answers.
    """
    path = path or "/manifest"
    try:
        with _client(HEALTH_TIMEOUT) as client:
            r = client.get(f"{address}{path}")
    except httpx.HTTPError as e:
        return "not_answering", unreachable(address, e)
    if not 200 <= r.status_code < 300:
        said = r.text.strip()[:300] if r.headers.get("content-type", "").startswith(("text/", "application/json")) else ""
        return "unwell", f"The plugin answered {r.status_code} to {path}" + (f": {said}" if said else ".")
    return "running", None


def host_of(address: str) -> str:
    return urlsplit(address).hostname or ""


def hosts_for(address: str) -> frozenset[str]:
    """The IP addresses the plugin's address stands for (its name looked up, remembered a minute); empty if unknown."""
    host = host_of(address)
    now = time.monotonic()
    hit = _resolved.get(host)
    if hit and now - hit[0] < RESOLVE_FOR:
        return hit[1]
    try:
        found = frozenset(normal_ip(info[4][0]) for info in socket.getaddrinfo(host, None))
    except (OSError, UnicodeError):
        found = frozenset()
    _resolved[host] = (now, found)
    return found


def normal_ip(ip: str) -> str:
    """An IP as compared: an IPv4 address carried in IPv6 (::ffff:1.2.3.4) is the IPv4 one."""
    try:
        parsed = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return ip
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(normal_ip(ip)).is_loopback
    except ValueError:
        return False


def from_address(client_ip: str | None, address: str) -> bool:
    """Whether a call from client_ip comes from the machine at the plugin's address."""
    if not client_ip:
        return False
    ip = normal_ip(client_ip)
    hosts = hosts_for(address)
    if ip in hosts:
        return True
    # a plugin on Farmhand's own machine, given as localhost: its calls come from loopback
    return is_loopback(ip) and any(is_loopback(h) for h in hosts)


def forget_resolved() -> None:
    _resolved.clear()
