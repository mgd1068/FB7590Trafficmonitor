# FritzReader – Bandbreitenmonitor für die FRITZ!Box

Ein kleines, eigenständiges Desktop-Tool zur Anzeige der aktuellen Upload- und Downloadraten einer FRITZ!Box – mit grafischer Darstellung in Echtzeit.

## Features

- Verbindung zur FRITZ!Box über `fritzconnection`
- Anzeige von Up-/Downloadraten in Mbit/s
- Live-Graph mit 3D-ähnlichem Look
- Dynamische Y-Achsen-Skalierung
- Gefüllte Flächen unter Kurven (Tron-Style)
- Rückblick auf bis zu 30 Minuten Bandbreitenverlauf
- Tooltip mit Werten beim Mouse-Hover
- Fensterposition speicherbar
- Immer-oben-Funktion (konfigurierbar)

## Voraussetzungen

- Python 3.10 oder höher empfohlen
- Installierte Abhängigkeiten (siehe unten)

## Installation

1. Repository klonen oder herunterladen  
2. Abhängigkeiten installieren:

```
pip install -r requirements.txt
```

3. Konfigurationsdatei `config.ini` anpassen (FRITZ!Box-IP, Benutzer, Passwort):

```
[FRITZBOX]
address = 192.168.178.1
username = benutzername
password = geheim

[WINDOW]
x = 100
y = 100
always_on_top = yes

[APP]
refresh_interval = 5  ; in Sekunden
```

## Start

```
python gui.py
```

## Projektstruktur

```
├── config.ini           # Konfigurationswerte
├── config.py            # Einlesen der Konfiguration
├── fritzreader.py       # Verbindung zur FRITZ!Box, Bandbreiten-Abfrage
├── gui.py               # GUI mit PyQt5 und pyqtgraph
├── requirements.txt     # Python-Abhängigkeiten
└── README.md            # Diese Datei
```

## Abhängigkeiten

- PyQt5
- pyqtgraph
- fritzconnection

## Hinweis

- Erfordert aktivierte UPnP- bzw. TR-064-Schnittstelle auf der FRITZ!Box.
- Bei älteren Firmware-Versionen ggf. eingeschränkte Funktionalität.
- Das Tool greift **lesend** auf den Router zu. Keine Konfiguration wird verändert.

## Lizenz

Apache-2.0 License
