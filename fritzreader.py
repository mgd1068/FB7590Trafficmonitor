"""
fritzreader.py
==============
Low-level FRITZ!Box data-retrieval layer for FB Speed Monitor.

This module owns the actual TR-064 / UPnP communication with the router and
exposes a clean, unit-testable API to the rest of the application.

Bandwidth measurement
---------------------
Three independent methods are tried in order of preference.  If a method
raises an exception **or** returns ``(None, None)``, the next one is
attempted automatically.  This three-tier fallback ensures compatibility
across FRITZ!Box firmware versions and model families:

1. :meth:`FritzReader._get_bandwidth_addon_infos`
   Uses the ``WANCommonIFC1 / GetAddonInfos`` action.  This is the
   preferred method because it returns instantaneous byte rates directly.

2. :meth:`FritzReader._get_bandwidth_traffic_stats`
   Uses the ``WANCommonIFC1 / X_AVM-DE_GetOnlineMonitor`` action.
   Available on more recent firmware versions.

3. :meth:`FritzReader._get_bandwidth_total_bytes`
   Derives rates from cumulative byte counters using ``GetTotalBytesReceived``
   / ``GetTotalBytesSent`` and a wall-clock time delta.  Always available but
   requires two successive calls to produce a result.

Plausibility filter
-------------------
Each successfully obtained value pair is compared against 150 % of the
reported line capacity.  Values outside that range are silently discarded
and replaced by the most recent valid measurement to prevent spurious spikes
in the graph.  If no prior measurement exists, ``(0.0, 0.0)`` is used.
"""

from fritzconnection import FritzConnection
from collections import deque
import time


class FritzReader:
    """Manages a single TR-064 connection and provides bandwidth data.

    Parameters
    ----------
    address : str
        IP address or hostname of the FRITZ!Box.
    username : str
        Login name (may be empty for boxes that use only a password).
    password : str
        Router password.
    history_size : int
        Maximum number of ``(dl, ul)`` measurement tuples retained in
        :attr:`history`.  At the default rate of one measurement every
        2 seconds, 360 entries cover the last 12 minutes.
    """

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        history_size: int = 360,
    ) -> None:
        self.address = address
        self.username = username
        self.password = password

        #: Ring buffer of ``(dl_mbit, ul_mbit)`` tuples (most recent last).
        self.history: deque = deque(maxlen=history_size)

        #: Active :class:`fritzconnection.FritzConnection` or ``None``.
        self.fc: FritzConnection | None = None

        # Internal state for the delta-byte fallback method
        self.last_rx_bytes: int = 0
        self.last_tx_bytes: int = 0
        self.last_time: float = 0.0

        #: When ``True``, successful method names are printed to stdout.
        self.debug: bool = False

        #: Session download peak in Mbit/s.
        self.max_dl: float = 0.0
        #: Session upload peak in Mbit/s.
        self.max_ul: float = 0.0

        #: Downstream line capacity in Mbit/s (read once at connect time).
        self.link_max_dl: float = 0.0
        #: Upstream line capacity in Mbit/s (read once at connect time).
        self.link_max_ul: float = 0.0

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config_obj, history_size: int = 360) -> "FritzReader":
        """Create a :class:`FritzReader` from a :class:`~config.Config` object.

        Parameters
        ----------
        config_obj : config.Config
            Application configuration.  Credentials are read from the
            ``[FRITZBOX]`` section.
        history_size : int
            Passed through to the constructor.
        """
        address, username, password = config_obj.get_fritzbox_credentials()
        return cls(address, username, password, history_size=history_size)

    @classmethod
    def from_device_info(
        cls, device_info, config_obj, history_size: int = 360
    ) -> "FritzReader":
        """Create a :class:`FritzReader` from a discovery result.

        Uses the IP from *device_info* but reads credentials from
        *config_obj*.  This supports the auto-discovery flow where the
        user selects a device found on the network without having to
        re-enter existing credentials.

        Parameters
        ----------
        device_info : fritz_discovery.DeviceInfo
            Device selected in the discovery dialog.
        config_obj : config.Config
            Source of login credentials.
        history_size : int
            Passed through to the constructor.
        """
        _, username, password = config_obj.get_fritzbox_credentials()
        return cls(device_info.ip, username, password, history_size=history_size)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def set_debug(self, debug: bool = True) -> None:
        """Enable or disable debug output to stdout."""
        self.debug = debug

    def connect(self) -> bool:
        """Open a TR-064 connection to the router and fetch line properties.

        The connection timeout is intentionally generous (12 s) to handle
        FRITZ!Boxes reachable only via slow VPN tunnels, where fetching the
        42+ service descriptions can take several seconds.

        Returns
        -------
        bool
            ``True`` on success, ``False`` when any exception occurs.
        """
        try:
            self.fc = FritzConnection(
                address=self.address,
                user=self.username,
                password=self.password,
                timeout=12.0,
            )
            print(f"[FritzReader] Connected to {self.fc.modelname} at {self.fc.address}")
            self._fetch_link_properties()
            return True
        except Exception as e:
            print(f"[FritzReader] Connection error: {e}")
            return False

    # ------------------------------------------------------------------
    # Bandwidth measurement
    # ------------------------------------------------------------------

    def get_bandwidth(self) -> tuple:
        """Return the current ``(download, upload)`` rate in Mbit/s.

        Tries up to three measurement methods in order.  Each method can
        signal "not available" by returning ``(None, None)`` – in that case
        the next method is tried.  After all methods are exhausted,
        ``(0.0, 0.0)`` is stored in the history and returned.

        The returned values are additionally filtered by the plausibility
        check (see module docstring).

        Returns
        -------
        tuple[float, float]
            ``(dl_mbit, ul_mbit)`` rounded to two decimal places.
        """
        if not self.fc:
            return 0.0, 0.0

        methods = [
            self._get_bandwidth_addon_infos,
            self._get_bandwidth_traffic_stats,
            self._get_bandwidth_total_bytes,
        ]

        for method in methods:
            try:
                rx, tx = method()
                if rx is None or tx is None:
                    continue  # Method signalled "not available"

                # --- Plausibility filter ---
                # Values exceeding 150 % of the rated line capacity are almost
                # certainly measurement artefacts (counter overflow, firmware
                # bug, etc.).  Replace them with the last known-good reading.
                brutto_limit_dl = (self.link_max_dl * 1.5) if self.link_max_dl > 0 else 2000
                brutto_limit_ul = (self.link_max_ul * 1.5) if self.link_max_ul > 0 else 2000

                if rx < 0 or tx < 0 or rx > brutto_limit_dl or tx > brutto_limit_ul:
                    print(
                        f"[FritzReader] Implausible value discarded: "
                        f"DL={rx:.2f} UL={tx:.2f} Mbit/s – repeating last good value."
                    )
                    if self.history:
                        last_good = self.history[-1]
                        self.history.append(last_good)
                        return last_good
                    else:
                        self.history.append((0.0, 0.0))
                        return 0.0, 0.0

                rx_r, tx_r = round(rx, 2), round(tx, 2)
                self.history.append((rx_r, tx_r))
                self.max_dl = max(self.max_dl, rx_r)
                self.max_ul = max(self.max_ul, tx_r)
                if self.debug:
                    print(f"[FritzReader] Successful method: {method.__name__}")
                return rx_r, tx_r

            except Exception as e:
                if self.debug:
                    print(f"[FritzReader] Method '{method.__name__}' failed: {e}")
                continue  # Try next method

        print("[FritzReader] All bandwidth methods failed.")
        self.history.append((0.0, 0.0))
        return 0.0, 0.0

    # ------------------------------------------------------------------
    # Private measurement methods
    # ------------------------------------------------------------------

    def _get_bandwidth_addon_infos(self) -> tuple:
        """Method 1: Read instantaneous byte rates from ``GetAddonInfos``.

        The ``NewByteReceiveRate`` / ``NewByteSendRate`` fields are
        directly in bytes/s.  If both are zero **and** no total-byte field
        is present the method is considered unavailable.

        Note: ``tx_rate == 0`` is a perfectly valid idle state and is **not**
        filtered here (the plausibility check in :meth:`get_bandwidth` is
        sufficient).
        """
        status = self.fc.call_action("WANCommonIFC1", "GetAddonInfos")
        rx_rate = int(status.get("NewByteReceiveRate", 0))
        tx_rate = int(status.get("NewByteSendRate", 0))
        # Both zero with no total-byte counter present → action not supported
        if rx_rate == 0 and tx_rate == 0 and status.get("NewTotalBytesSent") is None:
            return None, None
        return rx_rate * 8 / 1_000_000, tx_rate * 8 / 1_000_000

    def _get_bandwidth_traffic_stats(self) -> tuple:
        """Method 2: Read current rates from ``X_AVM-DE_GetOnlineMonitor``.

        The response dictionary contains keys whose names vary across
        firmware versions.  A flexible keyword search for ``"downstream"`` /
        ``"upstream"`` combined with ``"rate"`` / ``"bps"`` covers all known
        variants.  The largest matching value is used.
        """
        status = self.fc.call_action("WANCommonIFC1", "X_AVM-DE_GetOnlineMonitor")
        down_rate = 0
        up_rate = 0
        for key, value in status.items():
            key_lower = key.lower()
            if "downstream" in key_lower and ("rate" in key_lower or "bps" in key_lower):
                down_rate = max(down_rate, int(value))
            elif "upstream" in key_lower and ("rate" in key_lower or "bps" in key_lower):
                up_rate = max(up_rate, int(value))
        if down_rate > 0 or up_rate > 0:
            return down_rate / 1_000_000, up_rate / 1_000_000
        return None, None

    def _get_bandwidth_total_bytes(self) -> tuple:
        """Method 3: Derive rates from cumulative byte counters.

        Requires two consecutive calls separated by at least one tick of
        the system clock.  The first call stores the baseline and returns
        ``(None, None)``.  Subsequent calls compute the delta and convert
        it to Mbit/s using the elapsed wall-clock time.
        """
        status_rx = self.fc.call_action("WANCommonIFC1", "GetTotalBytesReceived")
        rx_total = int(status_rx.get("NewTotalBytesReceived", 0))
        status_tx = self.fc.call_action("WANCommonIFC1", "GetTotalBytesSent")
        tx_total = int(status_tx.get("NewTotalBytesSent", 0))

        current_time = time.time()
        if self.last_time > 0 and self.last_rx_bytes > 0:
            time_diff = current_time - self.last_time
            if time_diff > 0:
                rx_rate = (rx_total - self.last_rx_bytes) / time_diff
                tx_rate = (tx_total - self.last_tx_bytes) / time_diff
                self.last_rx_bytes = rx_total
                self.last_tx_bytes = tx_total
                self.last_time = current_time
                return rx_rate * 8 / 1_000_000, tx_rate * 8 / 1_000_000

        # First call – store baseline, no rate available yet
        self.last_rx_bytes = rx_total
        self.last_tx_bytes = tx_total
        self.last_time = current_time
        return None, None

    def _fetch_link_properties(self) -> None:
        """Query and cache the physical line capacity from the router.

        Called once during :meth:`connect`.  Sets :attr:`link_max_dl` and
        :attr:`link_max_ul`.  On failure both values are left at ``0.0``,
        which causes the plausibility filter to fall back to a 2 Gbit/s
        ceiling and the Y-axis to use the dynamic scaling mode.
        """
        try:
            props = self.fc.call_action("WANCommonIFC1", "GetCommonLinkProperties")
            self.link_max_dl = props.get("NewLayer1DownstreamMaxBitRate", 0) / 1_000_000
            self.link_max_ul = props.get("NewLayer1UpstreamMaxBitRate", 0) / 1_000_000
        except Exception as e:
            print(f"[FritzReader] Failed to fetch line properties: {e}")
            self.link_max_dl = 0.0
            self.link_max_ul = 0.0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_link_properties(self) -> tuple:
        """Return ``(link_max_dl, link_max_ul)`` in Mbit/s."""
        return self.link_max_dl, self.link_max_ul

    def get_maxima(self) -> tuple:
        """Return the session peak values ``(max_dl, max_ul)`` in Mbit/s."""
        return self.max_dl, self.max_ul

    def reset_maxima(self) -> None:
        """Reset session peak values to ``0.0`` (called on reconnect)."""
        self.max_dl = 0.0
        self.max_ul = 0.0

    def get_history(self) -> tuple:
        """Unpack :attr:`history` into two separate lists.

        Returns
        -------
        tuple[list[float], list[float]]
            ``(dl_values, ul_values)`` or ``([], [])`` when no data.
        """
        if not self.history:
            return [], []
        dl_list, ul_list = zip(*self.history)
        return list(dl_list), list(ul_list)

    def get_ip_addresses(self) -> tuple:
        """Return ``(lan_ip, wan_ip)`` strings.

        *lan_ip* is the router's LAN address (i.e. ``self.address``).
        *wan_ip* is the external/public IP address obtained from
        ``WANPPPConnection1 / GetInfo``.

        Returns
        -------
        tuple[str, str]
            On failure the WAN IP is replaced by an error class name.
        """
        try:
            lan_ip = self.fc.address
            status = self.fc.call_action("WANPPPConnection1", "GetInfo")
            wan_ip = status.get("NewExternalIPAddress", "N/A")
            return lan_ip, wan_ip
        except Exception as e:
            print(f"[FritzReader] IP address query failed: {e}")
            return (self.fc.address if self.fc else "N/A"), f"Error: {e.__class__.__name__}"

    def get_detailed_info(self) -> str:
        """Compile a verbose multi-line diagnostic string.

        Iterates over all WAN-related TR-064 services and actions whose
        names contain monitoring-related keywords.  The result is suitable
        for display in a read-only text dialog and is intended for
        troubleshooting purposes only.

        Returns
        -------
        str
            Multi-line text.  Returns ``"Not connected"`` when no active
            connection exists.
        """
        if not self.fc:
            return "Not connected"
        info = [
            f"Model:      {self.fc.modelname}",
            f"Address:    {self.fc.address}",
            f"Line:       ↓ {self.link_max_dl:.1f} / ↑ {self.link_max_ul:.1f} Mbit/s",
            "\n──────────────────────────────────────",
        ]
        wan_services = [s for s in self.fc.services.keys() if "WAN" in s]
        for service_name in sorted(wan_services):
            info.append(f"\n─── Service: {service_name} ───")
            try:
                service = self.fc.services[service_name]
                keywords = [
                    "status", "info", "stat", "byte",
                    "rate", "link", "connection", "monitor",
                ]
                for action_name in sorted(service.actions.keys()):
                    if any(k in action_name.lower() for k in keywords):
                        try:
                            result = self.fc.call_action(service_name, action_name)
                            info.append(f"  {action_name}:")
                            if isinstance(result, dict):
                                for key, value in result.items():
                                    info.append(f"    {key}: {value}")
                            else:
                                info.append(f"    {result}")
                        except Exception as e:
                            info.append(f"  {action_name}: (error: {e})")
            except Exception as e:
                info.append(f"  ERROR: {e}")
        return "\n".join(info)
