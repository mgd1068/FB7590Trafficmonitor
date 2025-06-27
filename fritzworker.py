# fritzworker.py
"""
Worker-Thread für die FB-Kommunikation, um die GUI nicht zu blockieren.
"""
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from fritzreader import FritzReader

class FritzWorker(QObject):
    """
    Dieser Worker läuft in einem separaten Thread und kümmert sich um die
    blockierenden Netzwerkaufrufe an die FRITZ!Box.
    """
    connection_status = pyqtSignal(dict)
    data_updated = pyqtSignal(dict)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.reader = None
        # --- KORREKTUR: Timer hier nur initialisieren, nicht erstellen ---
        self.timer = None
        self._is_running = True
        self._first_run = True

    def run(self):
        """Startet den Verbindungsaufbau und den Timer."""
        # --- KORREKTUR: Timer wird hier, im korrekten Thread, erstellt ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)

        self.reader = FritzReader.from_config(self.cfg)
        if self.reader.connect():
            status_dict = {
                'connected': True,
                'message': 'Verbunden',
                'details': {
                    'link_dl': self.reader.link_max_dl,
                    'link_ul': self.reader.link_max_ul,
                    'wan_ip': self.reader.get_ip_addresses()[1]
                },
                'first_run': self._first_run
            }
            self.connection_status.emit(status_dict)
            self.timer.start(self.cfg.get_refresh_interval() * 1000)
        else:
            status_dict = {
                'connected': False,
                'message': 'Verbindung fehlgeschlagen',
                'details': None,
                'first_run': self._first_run
            }
            self.connection_status.emit(status_dict)
        self._first_run = False

    def update_data(self):
        """Wird vom QTimer aufgerufen, um neue Bandbreitendaten abzufragen."""
        if not self._is_running:
            if self.timer: self.timer.stop()
            return

        try:
            down, up = self.reader.get_bandwidth()
            if down is None or up is None:
                raise ConnectionError("Ungültige Daten von der FB erhalten")

            self.data_updated.emit({
                'down': down,
                'up': up,
                'max_dl': self.reader.max_dl,
                'max_ul': self.reader.max_ul,
                'history': self.reader.history,
                'error': None
            })

        except Exception as e:
            print(f"[Worker] Fehler beim Datenabruf: {e}")
            self.data_updated.emit({'error': str(e)})
            if not self.reader.connect():
                print("[Worker] Neuverbindung fehlgeschlagen.")
            else:
                print("[Worker] Verbindung wiederhergestellt.")

    def reconnect(self):
        """Setzt die Verbindung und die Daten zurück."""
        if self.timer: self.timer.stop()
        if self.reader:
            self.reader.history.clear()
            self.reader.reset_maxima()
        self._first_run = True
        self.run()

    def stop(self):
        """Stoppt den Worker und den Timer."""
        self._is_running = False
        if self.timer: self.timer.stop()