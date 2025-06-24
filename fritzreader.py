# fritzreader.py
"""
Datenabfrage-Modul für FRITZ!Box: Holt Bandbreiteninformationen
und stellt optional die internen und externen IP-Adressen bereit.
Verwendet fritzconnection.
"""

from fritzconnection import FritzConnection
from collections import deque

class FritzReader:
    def __init__(self, address, username, password, history_size=360):
        self.address = address
        self.username = username
        self.password = password
        self.history = deque(maxlen=history_size)
        self.fc = None

    @classmethod
    def from_config(cls, history_size=360):
        from config import Config
        cfg = Config()
        address, username, password = cfg.get_fritzbox_credentials()
        return cls(address, username, password, history_size=history_size)

    def connect(self):
        try:
            self.fc = FritzConnection(address=self.address, user=self.username, password=self.password)
            print(f"[FritzReader] Verbunden mit {self.fc.modelname} at {self.fc.address}")
            return True
        except Exception as e:
            print(f"[FritzReader] Verbindungsfehler: {e}")
            return False

    def get_bandwidth(self):
        try:
            status = self.fc.call_action('WANCommonIFC1', 'GetAddonInfos')
            rx = int(status['NewByteReceiveRate']) * 8 / 1_000_000  # Mbit/s
            tx = int(status['NewByteSendRate']) * 8 / 1_000_000    # Mbit/s
            self.history.append((rx, tx))
            return round(rx, 2), round(tx, 2)
        except Exception as e:
            print(f"[FritzReader] Fehler beim Auslesen der Bandbreite: {e}")
            return 0.0, 0.0

    def get_history(self):
        dl = [round(p[0], 2) for p in self.history]
        ul = [round(p[1], 2) for p in self.history]
        return dl, ul

    def get_ip_addresses(self):
        try:
            # Interne IP direkt aus FritzConnection (meist die Adresse des Gateways)
            lan_ip = self.fc.address

            # Externe IP über WANIPConnection oder als Fallback WANPPPConnection
            try:
                wan_status = self.fc.call_action('WANIPConnection', 'GetExternalIPAddress')
            except Exception:
                wan_status = self.fc.call_action('WANPPPConnection', 'GetExternalIPAddress')

            wan_ip = wan_status.get('NewExternalIPAddress', 'n/a') if isinstance(wan_status, dict) else wan_status
            return lan_ip, wan_ip
        except Exception as e:
            print(f"[FritzReader] Fehler beim Abrufen der IP-Adressen: {e}")
            return "n/a", "n/a"
