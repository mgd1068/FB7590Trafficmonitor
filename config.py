import configparser
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.ini')

class Config:
    def __init__(self):
        self.config = configparser.ConfigParser()
        if not os.path.exists(CONFIG_PATH):
            raise FileNotFoundError(f"Keine config.ini gefunden unter: {CONFIG_PATH}")
        self.config.read(CONFIG_PATH, encoding='utf-8')

    def reload(self):
        """Lädt die Konfigurationsdatei neu."""
        self.config.read(CONFIG_PATH, encoding='utf-8')

    def get_fritzbox_credentials(self):
        section = self.config['FRITZBOX']
        return section.get('address'), section.get('username'), section.get('password')

    def get_window_position(self):
        section = self.config['WINDOW']
        return int(section.get('x', 100)), int(section.get('y', 100))

    def get_always_on_top(self):
        return self.config.getboolean('WINDOW', 'always_on_top', fallback=True)

    def get_refresh_interval(self):
        return int(self.config.get('APP', 'refresh_interval', fallback=2))
        
    def get_smoothing_enabled(self):
        return self.config.getboolean('APP', 'smoothing', fallback=False)

    # --- NEUE METHODE ---
    def get_yaxis_scaling_mode(self):
        """Gibt den Modus für die Skalierung der Y-Achse zurück."""
        return self.config.get('APP', 'yaxis_scaling', fallback='An Leitungskapazität anpassen')

    def get_animation_enabled(self):
        """NEU: Prüft, ob Animationen aktiv sind."""
        return self.config.getboolean('APP', 'animation', fallback=True)