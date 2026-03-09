"""
fritz_discovery.py
==================
Automatic FRITZ!Box discovery for FB Speed Monitor.

Discovery strategy
------------------
1. **SSDP / UPnP multicast** – Sends an ``M-SEARCH`` datagram to the
   standard multicast group ``239.255.255.250:1900`` using two common
   Internet-Gateway-Device service types.  Any host that replies is
   collected as a candidate IP.

2. **Fallback probe** – A hard-coded list of well-known FRITZ!Box addresses
   (``192.168.178.1``, ``fritz.box`` …) is probed sequentially after the
   multicast phase.  Addresses already found via SSDP are skipped.

For each candidate IP, a short :class:`fritzconnection.FritzConnection` is
attempted (no credentials required for device-description retrieval).
Successful connections are enriched with model-specific metadata from the
built-in :data:`MODEL_DB` lookup table and returned as :class:`DeviceInfo`
dataclass instances.

The public entry point :func:`discover_devices` is **blocking** and is
intended to be called only from a background thread (see
``fritzworker._DiscoveryThread`` in ``gui.py``).
"""

import socket
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Well-known fallback addresses tried when multicast SSDP finds nothing
# ---------------------------------------------------------------------------

#: Ordered list of candidate IPs / hostnames to probe as a fallback.
FALLBACK_IPS: List[str] = [
    "192.168.178.1",   # AVM factory default
    "192.168.2.1",     # Alternative subnet used by some configurations
    "192.168.1.1",     # Generic router default
    "192.168.0.1",     # Generic router default
    "fritz.box",       # mDNS hostname broadcast by every FRITZ!Box
]

# ---------------------------------------------------------------------------
# Model capability database
# ---------------------------------------------------------------------------

#: Maps model name prefixes to ``(technology_string, features_list)`` tuples.
#:
#: The lookup uses a case-insensitive *"is prefix in model name"* check, so
#: entries must be ordered from most-specific to least-specific when prefixes
#: overlap.
MODEL_DB = {
    "FRITZ!Box 7590 AX":    ("VDSL2/Supervectoring 35b", ["supervectoring", "wifi6"]),
    "FRITZ!Box 7590":       ("VDSL2/Supervectoring",     ["supervectoring"]),
    "FRITZ!Box 7530 AX":    ("VDSL2/Vectoring",          ["vectoring", "wifi6"]),
    "FRITZ!Box 7530":       ("VDSL2/Vectoring",          ["vectoring"]),
    "FRITZ!Box 7490":       ("VDSL2",                    []),
    "FRITZ!Box 7430":       ("ADSL2+",                   []),
    "FRITZ!Box 6690 Cable": ("DOCSIS 3.1",               ["cable", "wifi6"]),
    "FRITZ!Box 6591 Cable": ("DOCSIS 3.1",               ["cable"]),
    "FRITZ!Box 6660 Cable": ("DOCSIS 3.1",               ["cable", "wifi6"]),
    "FRITZ!Box 6490 Cable": ("DOCSIS 3.0",               ["cable"]),
    "FRITZ!Box 5590 Fiber": ("Glasfaser/XGS-PON",        ["fiber", "wifi6"]),
    "FRITZ!Box 5530 Fiber": ("Glasfaser/GPON",           ["fiber", "wifi6"]),
}


# ---------------------------------------------------------------------------
# Public data class
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Describes a discovered FRITZ!Box device.

    Attributes
    ----------
    ip : str
        Routable IP address (or hostname) used to reach the device.
    model : str
        Full model name as reported by the device, e.g.
        ``"FRITZ!Box 7590 AX"``.
    tech : str
        WAN technology string from :data:`MODEL_DB`, e.g.
        ``"VDSL2/Supervectoring"``.  Empty string when the model is not in
        the database.
    features : list[str]
        List of capability tags, e.g. ``["supervectoring", "wifi6"]``.
    """

    ip: str
    model: str = "FRITZ!Box"
    tech: str = ""
    features: list = field(default_factory=list)

    def display_name(self) -> str:
        """Return a human-readable one-liner, e.g. ``"FRITZ!Box 7590 AX  (192.168.2.1)"``."""
        return f"{self.model}  ({self.ip})"

    def has_feature(self, feature: str) -> bool:
        """Return ``True`` when *feature* is present in :attr:`features`."""
        return feature in self.features


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_model_caps(modelname: str):
    """Look up technology and feature list for a given model name string.

    Performs a case-insensitive sub-string search against :data:`MODEL_DB`
    keys.  Returns ``("", [])`` when no entry matches.

    Parameters
    ----------
    modelname : str
        The ``modelname`` attribute as returned by
        :class:`fritzconnection.FritzConnection`.

    Returns
    -------
    tuple[str, list[str]]
        ``(technology, features)`` pair.
    """
    for key, (tech, features) in MODEL_DB.items():
        if key.lower() in modelname.lower():
            return tech, list(features)
    return "", []


def _ssdp_search(timeout: float = 2.5) -> List[str]:
    """Broadcast SSDP ``M-SEARCH`` and collect responding IP addresses.

    Sends the request for two different UPnP service types to maximise
    compatibility across FRITZ!Box firmware generations.  The socket is
    closed after each attempt regardless of success or failure.

    Parameters
    ----------
    timeout : float
        How long to wait for responses, in seconds.

    Returns
    -------
    list[str]
        Deduplicated list of IP addresses that responded to the multicast.
        May be empty if multicast is blocked on the local network.
    """
    SSDP_ADDR = "239.255.255.250"
    SSDP_PORT = 1900
    found: set = set()

    for st in [
        "urn:dslforum-org:device:InternetGatewayDevice:1",
        "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    ]:
        msg = (
            "M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 2\r\n"
            f"ST: {st}\r\n"
            "\r\n"
        ).encode()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # TTL=4 allows the multicast to traverse a small number of routers
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
            sock.settimeout(timeout)
            sock.sendto(msg, (SSDP_ADDR, SSDP_PORT))
            try:
                while True:
                    _, addr = sock.recvfrom(4096)
                    found.add(addr[0])
            except socket.timeout:
                pass  # Normal end of the collection window
        except OSError:
            pass  # Multicast may not be available (e.g. VPN-only interface)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    return list(found)


def _try_connect(ip: str, timeout: float = 5.0) -> Optional[DeviceInfo]:
    """Attempt a credential-free :class:`fritzconnection.FritzConnection`.

    Only the device-description endpoint (``/igddesc.xml``) is fetched,
    which does not require authentication.  If the connection succeeds the
    model name is looked up in :data:`MODEL_DB` and a :class:`DeviceInfo`
    is returned.

    Parameters
    ----------
    ip : str
        Address to probe.
    timeout : float
        Per-request HTTP timeout in seconds.  Use a generous value for
        devices reachable only via VPN tunnels.

    Returns
    -------
    DeviceInfo | None
        Populated dataclass on success, ``None`` on any exception.
    """
    try:
        from fritzconnection import FritzConnection
        fc = FritzConnection(address=ip, timeout=timeout)
        modelname = fc.modelname or "FRITZ!Box"
        tech, features = _get_model_caps(modelname)
        return DeviceInfo(ip=ip, model=modelname, tech=tech, features=features)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_devices(progress_cb=None) -> List[DeviceInfo]:
    """Discover FRITZ!Box devices on the local network.

    This function is **blocking** and should be called from a background
    thread.  It first runs an SSDP multicast search, then probes the
    addresses in :data:`FALLBACK_IPS` that were not already found via SSDP.

    Parameters
    ----------
    progress_cb : callable[[str], None] | None
        Optional callback invoked with a short human-readable status string
        at each meaningful step (e.g. ``"Checking 192.168.178.1 …"``).
        Useful for driving a progress label in a UI dialog.

    Returns
    -------
    list[DeviceInfo]
        All reachable devices, in the order they were confirmed.  An empty
        list is returned when nothing could be reached.
    """
    results: List[DeviceInfo] = []
    checked: set = set()

    if progress_cb:
        progress_cb("Running SSDP/UPnP discovery …")

    ssdp_ips = _ssdp_search(timeout=2.5)
    # Merge SSDP results with fallback list, preserving SSDP results first
    all_ips = ssdp_ips + [ip for ip in FALLBACK_IPS if ip not in ssdp_ips]

    for ip in all_ips:
        if ip in checked:
            continue
        checked.add(ip)

        if progress_cb:
            progress_cb(f"Checking {ip} …")

        info = _try_connect(ip)
        if info:
            results.append(info)

    if progress_cb:
        if results:
            progress_cb(f"Found {len(results)} device(s).")
        else:
            progress_cb("No device found.")

    return results
