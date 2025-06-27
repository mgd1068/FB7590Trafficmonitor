# fritzreader.py
"""
Datenabfrage-Modul für FB: Holt Bandbreiteninformationen
und stellt optional die internen und externen IP-Adressen bereit.
Verwendet fritzconnection.
"""

from fritzconnection import FritzConnection
from collections import deque
import time

class FritzReader:
    def __init__(self, address, username, password, history_size=360):
        self.address = address
        self.username = username
        self.password = password
        self.history = deque(maxlen=history_size)
        self.fc = None
        self.last_rx_bytes = 0
        self.last_tx_bytes = 0
        self.last_time = 0
        self.debug = False
        self.max_dl = 0.0
        self.max_ul = 0.0
        self.link_max_dl = 0.0
        self.link_max_ul = 0.0

    @classmethod
    def from_config(cls, config_obj, history_size=360):
        address, username, password = config_obj.get_fritzbox_credentials()
        return cls(address, username, password, history_size=history_size)

    def set_debug(self, debug=True):
        self.debug = debug

    def connect(self):
        try:
            self.fc = FritzConnection(address=self.address, user=self.username, password=self.password, timeout=5.0)
            print(f"[FritzReader] Verbunden mit {self.fc.modelname} at {self.fc.address}")
            self._fetch_link_properties()
            return True
        except Exception as e:
            print(f"[FritzReader] Verbindungsfehler: {e}")
            return False

    def get_bandwidth(self):
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
                if rx is not None and tx is not None:
                    
                    # --- NEU: Plausibilitätsprüfung zur Vermeidung von Ausreissern ---
                    # Wir prüfen auf negative Werte oder Werte, die 150% der Leitungskapazität übersteigen.
                    # Ein Puffer von 50% ist sinnvoll, da die Brutto-Rate die Netto-Rate übersteigen kann.
                    brutto_limit_dl = (self.link_max_dl * 1.5) if self.link_max_dl > 0 else 2000 # Fallback auf 2 Gbit/s
                    brutto_limit_ul = (self.link_max_ul * 1.5) if self.link_max_ul > 0 else 2000 # Fallback

                    if rx < 0 or tx < 0 or rx > brutto_limit_dl or tx > brutto_limit_ul:
                        print(f"[FritzReader] Unrealistischer Wert erkannt und verworfen: DL={rx:.2f}, UL={tx:.2f}. Letzter Wert wird wiederholt.")
                        if self.history:
                            # Den letzten validen Wert erneut hinzufügen, um eine Lücke zu vermeiden
                            last_good_value = self.history[-1]
                            self.history.append(last_good_value)
                            return last_good_value
                        else:
                            # Falls der allererste Wert schon falsch ist
                            self.history.append((0.0, 0.0))
                            return 0.0, 0.0
                    # --- ENDE DER PRÜFUNG ---

                    rx_rounded, tx_rounded = round(rx, 2), round(tx, 2)
                    self.history.append((rx_rounded, tx_rounded))
                    self.max_dl = max(self.max_dl, rx_rounded)
                    self.max_ul = max(self.max_ul, tx_rounded)
                    if self.debug: print(f"[FritzReader] Erfolgreiche Methode: {method.__name__}")
                    return rx_rounded, tx_rounded
            except Exception as e:
                if self.debug: print(f"[FritzReader] Methode '{method.__name__}' schlug fehl: {e}")
                continue

        print("[FritzReader] Alle Methoden zur Bandbreitenmessung sind fehlgeschlagen.")
        self.history.append((0.0, 0.0))
        return 0.0, 0.0

    def _get_bandwidth_addon_infos(self):
        status = self.fc.call_action('WANCommonIFC1', 'GetAddonInfos')
        rx_rate = int(status.get('NewByteReceiveRate', 0))
        tx_rate = int(status.get('NewByteSendRate', 0))
        if rx_rate == 0 and tx_rate == 0 and status.get('NewTotalBytesSent') is not None:
            return None, None
        rx_mbits = rx_rate * 8 / 1_000_000
        tx_mbits = tx_rate * 8 / 1_000_000
        if rx_mbits > 0 and tx_mbits == 0:
            return None, None
        return rx_mbits, tx_mbits

    def _get_bandwidth_traffic_stats(self):
        status = self.fc.call_action("WANCommonIFC1", "X_AVM-DE_GetOnlineMonitor")
        down_rate_value = 0
        up_rate_value = 0
        for key, value in status.items():
            key_lower = key.lower()
            if 'downstream' in key_lower and ('rate' in key_lower or 'bps' in key_lower):
                 down_rate_value = max(down_rate_value, int(value))
            elif 'upstream' in key_lower and ('rate' in key_lower or 'bps' in key_lower):
                 up_rate_value = max(up_rate_value, int(value))
        if down_rate_value > 0 or up_rate_value > 0:
            return down_rate_value / 1_000_000, up_rate_value / 1_000_000
        return None, None

    def _get_bandwidth_total_bytes(self):
        status_rx = self.fc.call_action('WANCommonIFC1', 'GetTotalBytesReceived')
        rx_total = int(status_rx.get('NewTotalBytesReceived', 0))
        status_tx = self.fc.call_action('WANCommonIFC1', 'GetTotalBytesSent')
        tx_total = int(status_tx.get('NewTotalBytesSent', 0))
        current_time = time.time()
        if self.last_time > 0 and self.last_rx_bytes > 0:
            time_diff = current_time - self.last_time
            if time_diff > 0:
                rx_rate = (rx_total - self.last_rx_bytes) / time_diff
                tx_rate = (tx_total - self.last_tx_bytes) / time_diff
                self.last_rx_bytes, self.last_tx_bytes, self.last_time = rx_total, tx_total, current_time
                return rx_rate * 8 / 1_000_000, tx_rate * 8 / 1_000_000
        self.last_rx_bytes, self.last_tx_bytes, self.last_time = rx_total, tx_total, current_time
        return None, None
        
    def _fetch_link_properties(self):
        try:
            props = self.fc.call_action('WANCommonIFC1', 'GetCommonLinkProperties')
            self.link_max_dl = props.get('NewLayer1DownstreamMaxBitRate', 0) / 1_000_000
            self.link_max_ul = props.get('NewLayer1UpstreamMaxBitRate', 0) / 1_000_000
        except Exception as e:
            print(f"[FritzReader] Fehler beim Abrufen der Leitungsdaten: {e}")
            self.link_max_dl = 0.0
            self.link_max_ul = 0.0

    def get_link_properties(self):
        return self.link_max_dl, self.link_max_ul

    def get_maxima(self):
        return self.max_dl, self.max_ul

    def reset_maxima(self):
        self.max_dl = 0.0
        self.max_ul = 0.0

    def get_history(self):
        if not self.history: return [], []
        dl_list, ul_list = zip(*self.history)
        return list(dl_list), list(ul_list)

    def get_ip_addresses(self):
        try:
            lan_ip = self.fc.address
            status = self.fc.call_action('WANPPPConnection1', 'GetInfo')
            wan_ip = status.get('NewExternalIPAddress', 'N/A')
            return lan_ip, wan_ip
        except Exception as e:
            print(f"[FritzReader] IP-Abruf fehlgeschlagen: {e}")
            return (self.fc.address if self.fc else 'N/A'), f"Fehler: {e.__class__.__name__}"

    def get_detailed_info(self):
        if not self.fc: return "Nicht verbunden"
        info = [f"FB Modell: {self.fc.modelname}", f"Adresse: {self.fc.address}", "\n----------------------------------"]
        wan_services = [s for s in self.fc.services.keys() if 'WAN' in s]
        for service_name in sorted(wan_services):
            info.append(f"\n--- Service: {service_name} ---")
            try:
                service = self.fc.services[service_name]
                for action_name in sorted(service.actions.keys()):
                    if any(keyword in action_name.lower() for keyword in ['status', 'info', 'stat', 'byte', 'rate', 'link', 'connection', 'monitor']):
                        try:
                            result = self.fc.call_action(service_name, action_name)
                            info.append(f"  - {action_name}:")
                            if isinstance(result, dict):
                                for key, value in result.items(): info.append(f"    - {key}: {value}")
                            else: info.append(f"    - Result: {result}")
                        except Exception as e:
                            info.append(f"  - {action_name}: (Aktion schlug fehl: {e})")
            except Exception as e:
                 info.append(f"  FEHLER beim Abruf des Services: {e}")
        return "\n".join(info)