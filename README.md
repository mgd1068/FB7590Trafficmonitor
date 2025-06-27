# FB Speed Monitor

Ein leichtes, eigenständiges Desktop-Tool zur Anzeige der aktuellen Upload- und Downloadraten einer FRITZ!Box – mit grafischer Darstellung in Echtzeit, entwickelt für eine einfache "Auf einen Blick"-Übersicht.

## Features

- **Zuverlässige Datenabfrage:** Nutzt mehrere Methoden zur Abfrage der Bandbreitendaten, um mit verschiedenen FRITZ!Box-Modellen kompatibel zu sein.
- **Saubere Daten:** Eine integrierte Plausibilitätsprüfung filtert Messfehler und Ausreißer für eine stabile und korrekte grafische Darstellung.
- **Informatives Cockpit:**
    - Anzeige der Live-Raten für Up- und Download in farbcodierten Labels (Grün für Download, Rosa für Upload).
    - Anzeige der maximalen Leitungskapazität.
    - Anzeige der in der aktuellen Sitzung erreichten Spitzenwerte.
- **Interaktiver Live-Graph:**
    - Zeigt den Bandbreitenverlauf der letzten Minuten.
    - Ein Crosshair folgt der Maus und zeigt die exakten Werte zu einem beliebigen Zeitpunkt im Graphen an.
    - Der Graph signalisiert Verbindungsabbrüche mit einer deutlichen Text-Warnung.
- **Anpassbare Darstellung:**
    - Heller und dunkler Hintergrundmodus.
    - Zwei Kurven-Stile: "Neon-Lines" und "Gefüllte Flächen".
    - Flexible Darstellung des Upload-Graphen (überlagert oder gespiegelt).
    - Skalierung der Y-Achse wahlweise fest an der Leitungskapazität oder dynamisch am Spitzenwert.
- **Benutzerfreundlich:**
    - "Immer im Vordergrund"-Modus, um die Anzeige über anderen Fenstern zu halten.
    - Speichert die Fensterposition beim Schließen.
    - Führt den Benutzer beim ersten Start durch die Konfiguration.
    - Läuft dank Threading jederzeit flüssig, ohne die Oberfläche zu blockieren.

## Voraussetzungen

- Python 3.x
- Installierte Abhängigkeiten aus `requirements.txt`.

## Installation

1.  Repository klonen oder herunterladen.
2.  Abhängigkeiten installieren:
    ```
    pip install -r requirements.txt
    ```
3.  Die Anwendung beim ersten Start über den Einstellungsdialog konfigurieren (FRITZ!Box-IP, Benutzer, Passwort). Die Einstellungen werden in der `config.ini` gespeichert.

## Start

python gui.py


## Projektstruktur

├── config.ini           # Konfigurationswerte
├── config.py            # Einlesen der Konfiguration
├── fritzreader.py       # Verbindung zur FB & Bandbreiten-Abfrage
├── fritzworker.py       # Hintergrund-Thread für die Netzwerkkommunikation
├── gui.py               # Grafische Benutzeroberfläche mit PyQt5
├── requirements.txt     # Python-Abhängigkeiten
└── README.md            # Diese Datei


## Abhängigkeiten

- `PyQt5`
- `pyqtgraph`
- `fritzconnection`
- `numpy`
- `scipy` (Optional, für die Funktion "Kurven glätten")

## Hinweis

- Erfordert aktivierte UPnP- bzw. TR-064-Schnittstelle auf der FRITZ!Box.
- Das Tool greift **lesend** auf den Router zu. Keine Konfiguration wird verändert.

## Lizenz

Apache-2.0 License