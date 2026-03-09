"""
gui.py
======
Main application window and all UI components for FB Speed Monitor.

Architecture overview
---------------------
The GUI is structured as a single :class:`FritzMain` main window backed by a
:class:`~fritzworker.FritzWorker` that lives in a dedicated
:class:`~PyQt5.QtCore.QThread`.  All network I/O is confined to the worker
thread; the GUI thread only reacts to signals.

Key classes
~~~~~~~~~~~
:class:`_DiscoveryThread`
    Thin :class:`~PyQt5.QtCore.QThread` wrapper that calls
    :func:`~fritz_discovery.discover_devices` in the background and emits
    the result list when done.

:class:`DiscoveryDialog`
    Modal dialog shown when the initial connection fails.  Starts a
    :class:`_DiscoveryThread`, lists found devices, and lets the user
    pick one or fall back to manual configuration.

:class:`MetricCard`
    Compact :class:`~PyQt5.QtWidgets.QFrame` widget that displays one
    numeric metric (download, upload, peak DL, or peak UL).

:class:`ConfigDialog`
    Settings dialog for all application and connection parameters.
    Saves changes to ``config.ini`` and triggers a reconnect.

:class:`FritzMain`
    Main window.  Owns the :class:`~PyQt5.QtCore.QThread` / worker pair,
    drives the :mod:`pyqtgraph` live graph, and wires all signals.

Plot implementation notes
-------------------------
* Download and upload use **persistent** :class:`pyqtgraph.PlotCurveItem`
  objects.  The :class:`pyqtgraph.FillBetweenItem` instances connect to the
  curves' ``sigPlotChanged`` and update automatically – no per-frame
  remove/add cycle is needed.
* Curve style (Neon-Lines vs. Filled Areas) is applied only when the setting
  actually changes, avoiding redundant pen-object creation.
* Scipy PChip smoothing is applied with ``clip_negative=False`` when the
  "mirror upload" mode is active so that the reflected negative values are
  preserved correctly.

Color scheme
------------
Catppuccin Mocha palette:  dark navy background, green download, red/pink
upload, blue accent.  All colours are defined as module-level constants
(``C_*``) and injected into the application-wide Qt stylesheet.
"""

import os
import sys
import traceback
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QFont, QIcon, QPalette
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
    QSpinBox, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget,
)

from config import Config
from fritzworker import FritzWorker

try:
    from scipy.interpolate import PchipInterpolator
except ImportError:
    PchipInterpolator = None

# ---------------------------------------------------------------------------
# Catppuccin Mocha colour palette
# See https://github.com/catppuccin/catppuccin for the full spec.
# ---------------------------------------------------------------------------
C_BG      = "#1e1e2e"  #: Darkest base background
C_MANTLE  = "#181825"  #: Slightly darker surface (menu bar, status bar)
C_SURFACE = "#313244"  #: Card and widget backgrounds
C_OVERLAY = "#585b70"  #: Borders, disabled text, grid lines
C_TEXT    = "#cdd6f4"  #: Primary foreground text
C_SUBTEXT = "#a6adc8"  #: Secondary / dimmed text
C_DL      = "#a6e3a1"  #: Download colour (green)
C_UL      = "#f38ba8"  #: Upload colour (red/pink)
C_ACCENT  = "#89b4fa"  #: Accent / interactive highlight (blue)
C_WARN    = "#f9e2af"  #: Warning colour (yellow)  – reserved for future use
C_ERR     = "#f38ba8"  #: Error overlay colour (same hue as upload)

STYLESHEET = f"""
QMainWindow, QDialog, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-size: 12px;
}}
QMenuBar {{
    background-color: {C_MANTLE};
    color: {C_TEXT};
    border-bottom: 1px solid {C_OVERLAY};
    padding: 2px;
}}
QMenuBar::item:selected {{ background-color: {C_OVERLAY}; border-radius: 3px; }}
QMenu {{
    background-color: {C_SURFACE};
    color: {C_TEXT};
    border: 1px solid {C_OVERLAY};
    border-radius: 4px;
    padding: 4px;
}}
QMenu::item {{ padding: 4px 20px; border-radius: 3px; }}
QMenu::item:selected {{ background-color: {C_OVERLAY}; }}
QMenu::separator {{ height: 1px; background: {C_OVERLAY}; margin: 3px 6px; }}
QStatusBar {{
    background-color: {C_MANTLE};
    color: {C_SUBTEXT};
    border-top: 1px solid {C_OVERLAY};
    font-size: 11px;
}}
QPushButton {{
    background-color: {C_SURFACE};
    color: {C_TEXT};
    border: 1px solid {C_OVERLAY};
    border-radius: 5px;
    padding: 6px 14px;
    min-width: 80px;
}}
QPushButton:hover {{ background-color: {C_OVERLAY}; border-color: {C_ACCENT}; }}
QPushButton:pressed {{ background-color: {C_ACCENT}; color: {C_BG}; }}
QPushButton:default {{ border-color: {C_ACCENT}; }}
QPushButton:disabled {{ color: {C_OVERLAY}; border-color: {C_SURFACE}; }}
QLineEdit, QSpinBox, QComboBox, QTextEdit {{
    background-color: {C_SURFACE};
    color: {C_TEXT};
    border: 1px solid {C_OVERLAY};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {C_ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border-color: {C_ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background-color: {C_SURFACE};
    color: {C_TEXT};
    selection-background-color: {C_OVERLAY};
    border: 1px solid {C_OVERLAY};
    border-radius: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {C_OVERLAY};
    border-radius: 2px;
    width: 16px;
}}
QCheckBox {{ color: {C_TEXT}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {C_OVERLAY};
    border-radius: 3px;
    background-color: {C_SURFACE};
}}
QCheckBox::indicator:checked {{ background-color: {C_ACCENT}; border-color: {C_ACCENT}; }}
QCheckBox::indicator:disabled {{ background-color: {C_MANTLE}; }}
QLabel {{ color: {C_TEXT}; }}
QFrame#MetricCard {{
    background-color: {C_SURFACE};
    border-radius: 8px;
    border: 1px solid {C_OVERLAY};
}}
QListWidget {{
    background-color: {C_SURFACE};
    color: {C_TEXT};
    border: 1px solid {C_OVERLAY};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item {{ padding: 6px 4px; border-radius: 3px; }}
QListWidget::item:selected {{ background-color: {C_OVERLAY}; }}
QProgressBar {{
    background-color: {C_SURFACE};
    border: 1px solid {C_OVERLAY};
    border-radius: 3px;
    text-align: center;
    color: {C_TEXT};
}}
QProgressBar::chunk {{ background-color: {C_ACCENT}; border-radius: 2px; }}
QScrollBar:vertical {{
    background: {C_MANTLE}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {C_OVERLAY}; border-radius: 4px; min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""


# ---------------------------------------------------------------------------
# Discovery thread
# ---------------------------------------------------------------------------

class _DiscoveryThread(QThread):
    """Background thread that runs :func:`~fritz_discovery.discover_devices`.

    Signals
    -------
    progress : str
        Human-readable status string forwarded from
        :func:`~fritz_discovery.discover_devices`'s ``progress_cb``.
    result : list[fritz_discovery.DeviceInfo]
        Emitted once when discovery completes (may be an empty list).
    """

    progress = pyqtSignal(str)
    result   = pyqtSignal(list)

    def run(self) -> None:
        """Execute blocking discovery and emit :attr:`result` when done."""
        from fritz_discovery import discover_devices
        devices = discover_devices(progress_cb=self.progress.emit)
        self.result.emit(devices)


# ---------------------------------------------------------------------------
# Discovery dialog
# ---------------------------------------------------------------------------

class DiscoveryDialog(QDialog):
    """Modal dialog for automatic FRITZ!Box discovery.

    Opens a :class:`_DiscoveryThread` immediately on construction, shows
    an indeterminate progress bar while the search is running, and
    populates a list widget with the found devices.

    Signals
    -------
    device_selected : fritz_discovery.DeviceInfo
        Emitted when the user clicks *Connect* after selecting a device.
        The main window connects this to
        :meth:`FritzMain._on_device_selected`.
    """

    device_selected = pyqtSignal(object)  # DeviceInfo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FRITZ!Box suchen")
        self.setModal(True)
        self.setMinimumSize(500, 320)
        self._found = []
        self._thread = None
        self._init_ui()
        self._start_search()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("FRITZ!Box automatisch suchen")
        title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {C_ACCENT};")
        layout.addWidget(title)

        self._status_label = QLabel("Bitte warten...")
        self._status_label.setStyleSheet(f"color: {C_SUBTEXT}; font-size: 11px;")
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(5)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemDoubleClicked.connect(self._on_connect)
        layout.addWidget(self._list)

        btn_layout = QHBoxLayout()
        self._connect_btn = QPushButton("Verbinden")
        self._connect_btn.setEnabled(False)
        self._connect_btn.setDefault(True)
        self._connect_btn.clicked.connect(self._on_connect)
        self._connect_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_ACCENT}; color: {C_BG}; border-color: {C_ACCENT}; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {C_OVERLAY}; color: {C_TEXT}; }}"
        )

        self._rescan_btn = QPushButton("Erneut suchen")
        self._rescan_btn.clicked.connect(self._start_search)

        self._manual_btn = QPushButton("Manuell konfigurieren")
        self._manual_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self._connect_btn)
        btn_layout.addWidget(self._rescan_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._manual_btn)
        layout.addLayout(btn_layout)

    def _start_search(self):
        self._found = []
        self._list.clear()
        self._connect_btn.setEnabled(False)
        self._progress.setRange(0, 0)
        self._status_label.setText("Suche läuft...")

        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)

        self._thread = _DiscoveryThread()
        self._thread.progress.connect(self._status_label.setText)
        self._thread.result.connect(self._on_result)
        self._thread.start()

    def _on_result(self, devices):
        self._found = devices
        self._progress.setRange(0, 1)
        self._progress.setValue(1)

        if devices:
            for d in devices:
                tech_str = f"  –  {d.tech}" if d.tech else ""
                label = f"  {d.model}{tech_str}   [{d.ip}]"
                item = QListWidgetItem(label)
                feat_str = ", ".join(d.features) if d.features else "–"
                item.setToolTip(f"IP: {d.ip}\nTechnologie: {d.tech or 'unbekannt'}\nFeatures: {feat_str}")
                self._list.addItem(item)
            self._list.setCurrentRow(0)
            self._connect_btn.setEnabled(True)
            self._status_label.setText(f"{len(devices)} Gerät(e) gefunden – bitte auswählen und verbinden.")
        else:
            self._status_label.setText(
                "Keine FRITZ!Box gefunden. Bitte Netzwerk prüfen oder manuell konfigurieren."
            )

    def _on_connect(self, *_):
        row = self._list.currentRow()
        if 0 <= row < len(self._found):
            self.device_selected.emit(self._found[row])
            self.accept()

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Metric card widget
# ---------------------------------------------------------------------------

class MetricCard(QFrame):
    """Compact card widget that displays a single numeric metric.

    Renders three stacked labels:

    1. A coloured **title** line (e.g. "↓  Download").
    2. A large **value** in the same accent colour.
    3. A dimmed **unit** label ("Mbit/s").

    The card is styled via the ``QFrame#MetricCard`` QSS rule defined in
    :data:`STYLESHEET`.

    Parameters
    ----------
    title : str
        Short label shown above the value.
    color : str
        CSS hex colour string applied to both the title and value labels.
    """

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(120)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(2)
        layout.setContentsMargins(12, 10, 12, 10)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; background: transparent; border: none;")

        self._value_lbl = QLabel("–")
        self._value_lbl.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(22)
        font.setBold(True)
        font.setStyleStrategy(QFont.PreferAntialias)
        self._value_lbl.setFont(font)
        self._value_lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")

        self._unit_lbl = QLabel("Mbit/s")
        self._unit_lbl.setAlignment(Qt.AlignCenter)
        self._unit_lbl.setStyleSheet(f"color: {C_SUBTEXT}; font-size: 10px; background: transparent; border: none;")

        layout.addWidget(self._title_lbl)
        layout.addWidget(self._value_lbl)
        layout.addWidget(self._unit_lbl)

    def set_value(self, val: float):
        self._value_lbl.setText(f"{val:.2f}" if val >= 0 else "–")

    def set_title(self, title: str):
        self._title_lbl.setText(title)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class ConfigDialog(QDialog):
    """Application settings dialog.

    Presents all configurable parameters in a :class:`~PyQt5.QtWidgets.QFormLayout`.
    On *Accept*, values are written to ``config.ini`` and the dialog closes.
    The caller is responsible for reloading the config and triggering a
    reconnect if necessary (see :meth:`FritzMain._open_config`).
    """

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("FB Speed – Einstellungen")
        self.setModal(True)
        self.setFixedSize(420, 440)
        self._init_ui()

    def _init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setLabelAlignment(Qt.AlignRight)

        try:
            addr, usr, pwd = self.cfg.get_fritzbox_credentials()
        except Exception:
            addr, usr, pwd = "192.168.178.1", "", ""

        self.address_edit = QLineEdit(addr or "192.168.178.1")
        self.user_edit = QLineEdit(usr or "")
        self.pass_edit = QLineEdit(pwd or "")
        self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addRow("FRITZ!Box-Adresse:", self.address_edit)
        layout.addRow("Benutzer:", self.user_edit)
        layout.addRow("Passwort:", self.pass_edit)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(1, 60)
        self.refresh_spin.setValue(self.cfg.get_refresh_interval())
        self.refresh_spin.setSuffix(" s")
        layout.addRow("Aktualisierung:", self.refresh_spin)

        self.always_top_check = QCheckBox()
        self.always_top_check.setChecked(self.cfg.get_always_on_top())
        layout.addRow("Immer im Vordergrund:", self.always_top_check)

        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["schwarz", "weiss"])
        self.bg_combo.setCurrentText(self.cfg.get_bg())
        layout.addRow("Hintergrund:", self.bg_combo)

        self.style_combo = QComboBox()
        self.style_combo.addItems(["Neon-Lines", "Gefüllte Flächen"])
        self.style_combo.setCurrentText(self.cfg.get_style())
        layout.addRow("Kurven-Stil:", self.style_combo)

        self.ulmode_combo = QComboBox()
        self.ulmode_combo.addItems(["Überlagert", "Spiegeln unter 0"])
        self.ulmode_combo.setCurrentText(self.cfg.get_ulmode())
        layout.addRow("Upload-Anzeige:", self.ulmode_combo)

        self.yaxis_combo = QComboBox()
        self.yaxis_combo.addItems(["An Leitungskapazität anpassen", "Dynamisch an Spitzenwert"])
        self.yaxis_combo.setCurrentText(self.cfg.get_yaxis_scaling_mode())
        layout.addRow("Y-Achsen-Skalierung:", self.yaxis_combo)

        self.smoothing_check = QCheckBox()
        self.smoothing_check.setChecked(self.cfg.get_smoothing_enabled())
        if PchipInterpolator is None:
            self.smoothing_check.setEnabled(False)
            self.smoothing_check.setToolTip("Benötigt 'scipy': pip install scipy")
        layout.addRow("Kurven glätten:", self.smoothing_check)

        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Übernehmen")
        ok_btn.setDefault(True)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_ACCENT}; color: {C_BG}; border-color: {C_ACCENT}; font-weight: bold; }}"
        )
        cancel_btn = QPushButton("Abbrechen")
        ok_btn.clicked.connect(self._apply)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def _apply(self):
        for section in ["FRITZBOX", "WINDOW", "APP"]:
            if section not in self.cfg.config:
                self.cfg.config.add_section(section)
        self.cfg.config["FRITZBOX"]["address"] = self.address_edit.text().strip()
        self.cfg.config["FRITZBOX"]["username"] = self.user_edit.text().strip()
        self.cfg.config["FRITZBOX"]["password"] = self.pass_edit.text().strip()
        self.cfg.config["APP"]["refresh_interval"] = str(self.refresh_spin.value())
        self.cfg.config["APP"]["bg"] = self.bg_combo.currentText()
        self.cfg.config["APP"]["style"] = self.style_combo.currentText()
        self.cfg.config["APP"]["ulmode"] = self.ulmode_combo.currentText()
        self.cfg.config["APP"]["yaxis_scaling"] = self.yaxis_combo.currentText()
        self.cfg.config["WINDOW"]["always_on_top"] = "yes" if self.always_top_check.isChecked() else "no"
        self.cfg.config["APP"]["smoothing"] = "yes" if self.smoothing_check.isChecked() else "no"
        try:
            with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f:
                self.cfg.config.write(f)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Konfiguration konnte nicht gespeichert werden:\n{e}")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class FritzMain(QMainWindow):
    """Main application window.

    Owns the worker thread, the live graph, and all UI state.

    Signal/slot wiring
    ------------------
    The three private class-level signals below are used exclusively to
    forward GUI-initiated actions to the worker thread.  Because
    :class:`~fritzworker.FritzWorker` lives in a different thread, Qt
    automatically uses a *queued connection*, ensuring the slots execute
    inside the worker thread's event loop.

    ``_reconnect_signal``
        Triggers :meth:`~fritzworker.FritzWorker.reconnect`.
    ``_debug_request``
        Triggers :meth:`~fritzworker.FritzWorker.fetch_debug_info`.
    ``_set_device_signal``
        Triggers :meth:`~fritzworker.FritzWorker.set_device_and_reconnect`
        with a :class:`~fritz_discovery.DeviceInfo` argument.
    """

    # Private signals for GUI → Worker cross-thread calls (QueuedConnection)
    _reconnect_signal  = pyqtSignal()
    _debug_request     = pyqtSignal()
    _set_device_signal = pyqtSignal(object)   # DeviceInfo

    def __init__(self):
        super().__init__()
        self._hist_snapshot = []    # Thread-sicherer Snapshot für Crosshair
        self.link_dl = 0.0
        self.link_ul = 0.0
        self._current_style = None  # Cache für Stil-Änderungen
        self._tray = None
        self._debug_dialog = None

        try:
            self._init_config()
            self._init_ui()
            self._start_worker()
        except Exception as e:
            QMessageBox.critical(
                self, "Initialisierungsfehler",
                f"Fehler beim Starten:\n{e}\n\n{traceback.format_exc()}"
            )
            sys.exit(1)

    # ── Konfiguration ──────────────────────────────────────────────────────

    def _init_config(self):
        config_file = Path(__file__).parent / "config.ini"
        if not config_file.exists():
            self._create_default_config()
        self.cfg = Config()

    def _create_default_config(self):
        default = (
            "[FRITZBOX]\n"
            "address = 192.168.178.1\n"
            "username = \n"
            "password = \n"
            "[WINDOW]\n"
            "x = 100\n"
            "y = 100\n"
            "always_on_top = yes\n"
            "[APP]\n"
            "refresh_interval = 2\n"
            "bg = schwarz\n"
            "style = Neon-Lines\n"
            "ulmode = Überlagert\n"
            "smoothing = no\n"
            "animation = yes\n"
            "yaxis_scaling = An Leitungskapazität anpassen\n"
        )
        with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f:
            f.write(default)

    # ── UI aufbauen ────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("FB Speed Monitor")
        self.setMinimumSize(700, 480)
        self._create_menubar()

        container = QWidget(self)
        self.setCentralWidget(container)
        vbox = QVBoxLayout(container)
        vbox.setSpacing(8)
        vbox.setContentsMargins(10, 8, 10, 8)

        # Metric Cards (DL / UL / Peak DL / Peak UL)
        vbox.addLayout(self._build_cards_row())

        # Leitung / IP Info
        self.ip_label = QLabel("Verbinde...")
        self.ip_label.setAlignment(Qt.AlignCenter)
        self.ip_label.setStyleSheet(f"color: {C_SUBTEXT}; font-size: 11px;")
        vbox.addWidget(self.ip_label)

        # Live-Graph
        self.plot_widget = pg.PlotWidget()
        vbox.addWidget(self.plot_widget, stretch=1)

        self._setup_plot()
        self._setup_tray()
        self._setup_window_geometry()

    def _build_cards_row(self) -> QHBoxLayout:
        """Erstellt die Zeile mit den vier Metric-Cards."""
        self._card_dl      = MetricCard("↓  Download",  C_DL)
        self._card_ul      = MetricCard("↑  Upload",    C_UL)
        self._card_peak_dl = MetricCard("↓  Peak DL",  C_DL)
        self._card_peak_ul = MetricCard("↑  Peak UL",  C_UL)

        row = QHBoxLayout()
        row.setSpacing(8)
        for card in (self._card_dl, self._card_ul, self._card_peak_dl, self._card_peak_ul):
            row.addWidget(card)
        return row

    def _create_menubar(self):
        mbar = self.menuBar()
        mbar.setNativeMenuBar(False)

        cfg_menu = mbar.addMenu("&Konfiguration")
        act_cfg = QAction("&Einstellungen…", self, shortcut="Ctrl+,")
        act_cfg.triggered.connect(self._open_config)
        cfg_menu.addAction(act_cfg)

        act_search = QAction("&FRITZ!Box suchen…", self, shortcut="Ctrl+F")
        act_search.triggered.connect(self._open_discovery_dialog)
        cfg_menu.addAction(act_search)

        cfg_menu.addSeparator()
        act_reconnect = QAction("&Neu verbinden", self, shortcut="F5")
        act_reconnect.triggered.connect(self._reconnect)
        cfg_menu.addAction(act_reconnect)

        debug_menu = mbar.addMenu("&Debug")
        act_debug = QAction("&Debug-Informationen…", self)
        act_debug.triggered.connect(self._show_debug_info)
        debug_menu.addAction(act_debug)

        help_menu = mbar.addMenu("&Hilfe")
        act_about = QAction("&Über…", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _setup_plot(self):
        bg = C_BG if self.cfg.get_bg() == "schwarz" else "#eff1f5"
        self.plot_widget.setBackground(QColor(bg))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setLabel("left", "Bandbreite (Mbit/s)")
        self.plot_widget.setLabel("bottom", "Zeit (Messpunkte)")

        # Persistente Kurven und Fill-Bereiche (kein Rebuild bei jedem Update!)
        self.dl_curve = pg.PlotCurveItem(pen=pg.mkPen(color=C_DL, width=2), name="↓ Download")
        self.ul_curve = pg.PlotCurveItem(pen=pg.mkPen(color=C_UL, width=2), name="↑ Upload")
        self._dl_zero = pg.PlotCurveItem(pen=None)   # Basislinie für Download-Fill
        self._ul_zero = pg.PlotCurveItem(pen=None)   # Basislinie für Upload-Fill

        # FillBetweenItem verbindet sich mit sigPlotChanged der Kurven → auto-update!
        self._dl_fill = pg.FillBetweenItem(self.dl_curve, self._dl_zero,
                                            brush=pg.mkBrush(QColor(C_DL + "50")))
        self._ul_fill = pg.FillBetweenItem(self.ul_curve, self._ul_zero,
                                            brush=pg.mkBrush(QColor(C_UL + "50")))

        # Reihenfolge: Fills unter Kurven
        for item in (self._dl_zero, self._ul_zero, self._dl_fill, self._ul_fill,
                     self.dl_curve, self.ul_curve):
            self.plot_widget.addItem(item)

        # Legende
        legend = self.plot_widget.addLegend(offset=(10, 10))
        legend.addItem(self.dl_curve, "↓ Download")
        legend.addItem(self.ul_curve, "↑ Upload")

        # Crosshair
        self._crosshair_v = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(color=C_OVERLAY, style=Qt.DashLine, width=1)
        )
        self._crosshair_label = pg.TextItem(anchor=(0, 1))
        self.plot_widget.addItem(self._crosshair_v, ignoreBounds=True)
        self.plot_widget.addItem(self._crosshair_label, ignoreBounds=True)
        self._plot_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=60, slot=self._mouse_moved
        )

        # Fehler-Overlay
        self._error_item = pg.TextItem("", color=C_ERR, anchor=(0.5, 0.5))
        self._error_item.setFont(QFont("", 16, QFont.Bold))
        self.plot_widget.addItem(self._error_item)
        self._error_item.hide()

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(QIcon(), self)
        tmenu = QMenu()
        show_action = tmenu.addAction("Anzeigen")
        show_action.triggered.connect(self.showNormal)
        show_action.triggered.connect(self.raise_)
        tmenu.addSeparator()
        quit_action = tmenu.addAction("Beenden")
        quit_action.triggered.connect(self._quit_application)
        self._tray.setContextMenu(tmenu)
        self._tray.setToolTip("FB Speed Monitor")
        self._tray.show()
        self._tray.activated.connect(self._tray_activated)

    def _setup_window_geometry(self):
        self.resize(900, 560)
        try:
            x, y = self.cfg.get_window_position()
            self.move(x, y)
            if self.cfg.get_always_on_top():
                self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        except Exception as e:
            print(f"Fehler bei Fenster-Setup: {e}")

    # ── Worker starten ────────────────────────────────────────────────────

    def _start_worker(self):
        self.thread = QThread()
        self.worker = FritzWorker(self.cfg)
        self.worker.moveToThread(self.thread)

        # Worker-Signale → GUI-Slots
        self.thread.started.connect(self.worker.run)
        self.worker.connection_status.connect(self._handle_connection_status)
        self.worker.data_updated.connect(self._handle_data_update)
        self.worker.discovery_needed.connect(self._open_discovery_dialog)
        self.worker.debug_info_ready.connect(self._handle_debug_info)

        # GUI-Signale → Worker-Slots (QueuedConnection, da verschiedene Threads)
        self._reconnect_signal.connect(self.worker.reconnect)
        self._debug_request.connect(self.worker.fetch_debug_info)
        self._set_device_signal.connect(self.worker.set_device_and_reconnect)

        self.thread.start()

    # ── Daten-Handler ─────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def _handle_connection_status(self, status):
        self.statusBar().showMessage(status["message"], 4000)
        if status["connected"]:
            details = status["details"]
            self.link_dl = details["link_dl"]
            self.link_ul = details["link_ul"]
            model = details.get("model", "")
            wan_ip = details["wan_ip"]

            # Fenstertitel mit Modellname
            if model:
                self.setWindowTitle(f"FB Speed Monitor  –  {model}")

            if self.link_dl > 0:
                ip_html = (
                    f"<b>{model}</b>  |  "
                    f"Leitung: <b>↓</b> <font color='{C_DL}'>{self.link_dl:.1f}</font> / "
                    f"<b>↑</b> <font color='{C_UL}'>{self.link_ul:.1f}</font> Mbit/s  |  "
                    f"WAN: {wan_ip}"
                )
            else:
                ip_html = f"<b>{model}</b>  |  WAN: {wan_ip}"
            self.ip_label.setText(ip_html)
        else:
            self.ip_label.setText(
                f"<font color='{C_ERR}'>Verbindung zur FRITZ!Box fehlgeschlagen</font>"
            )

    @pyqtSlot(dict)
    def _handle_data_update(self, data):
        if data.get("error"):
            self._error_item.setText("Verbindungsproblem!")
            vb = self.plot_widget.getViewBox()
            r = vb.viewRange()
            cx = (r[0][0] + r[0][1]) / 2
            cy = (r[1][0] + r[1][1]) / 2
            self._error_item.setPos(cx, cy)
            self._error_item.show()
            return

        self._error_item.hide()
        down, up = data["down"], data["up"]
        max_dl, max_ul = data["max_dl"], data["max_ul"]

        # Thread-sicherer Snapshot für Crosshair-Zugriff
        self._hist_snapshot = list(data["history"])

        # Metric Cards aktualisieren
        self._card_dl.set_value(down)
        self._card_ul.set_value(up)
        self._card_peak_dl.set_value(max_dl)
        self._card_peak_ul.set_value(max_ul)

        # Tray-Tooltip
        if self._tray:
            self._tray.setToolTip(f"FB Speed\n↓ {down:.2f}  ↑ {up:.2f} Mbit/s")

        self._update_plot()

    # ── Graph-Rendering ───────────────────────────────────────────────────

    def _mouse_moved(self, event):
        if not self._hist_snapshot:
            return
        pos = event[0]
        if not self.plot_widget.sceneBoundingRect().contains(pos):
            return
        mp = self.plot_widget.getViewBox().mapSceneToView(pos)
        idx = int(mp.x())
        if 0 <= idx < len(self._hist_snapshot):
            dl, ul = self._hist_snapshot[idx]
            self._crosshair_v.setPos(mp.x())
            self._crosshair_label.setHtml(
                f"<div style='background:{C_SURFACE};color:{C_TEXT};"
                f"padding:5px;border-radius:4px;border:1px solid {C_OVERLAY};'>"
                f"<font color='{C_DL}'>↓ {dl:.2f}</font><br>"
                f"<font color='{C_UL}'>↑ {ul:.2f}</font></div>"
            )
            self._crosshair_label.setPos(mp.x(), mp.y())

    def _update_plot(self):
        if not self._hist_snapshot:
            return

        n = len(self._hist_snapshot)
        x_base = np.arange(n, dtype=float)
        dl_y = np.array([p[0] for p in self._hist_snapshot])
        ul_y = np.array([p[1] for p in self._hist_snapshot])

        ulmode = self.cfg.get_ulmode()
        is_mirrored = ulmode.startswith("Spiegel")
        if is_mirrored:
            ul_y = -ul_y

        smoothing = self.cfg.get_smoothing_enabled()
        if smoothing:
            # Bug-Fix: clip_negative=False wenn Spiegel-Modus, damit negative UL-Werte erhalten bleiben
            dl_x, dl_y = self._get_smoothed_data(x_base, dl_y, clip_negative=True)
            ul_x, ul_y = self._get_smoothed_data(x_base, ul_y, clip_negative=not is_mirrored)
        else:
            dl_x = ul_x = x_base

        # Kurven aktualisieren – FillBetweenItem aktualisiert sich automatisch!
        self.dl_curve.setData(dl_x, dl_y)
        self.ul_curve.setData(ul_x, ul_y)
        self._dl_zero.setData(dl_x, np.zeros(len(dl_x)))
        self._ul_zero.setData(ul_x, np.zeros(len(ul_x)))

        # Stil nur aktualisieren wenn sich etwas geändert hat
        self._apply_style()

        # Y-Achse skalieren
        dl_hist_vals = [p[0] for p in self._hist_snapshot]
        scaling = self.cfg.get_yaxis_scaling_mode()
        if scaling.startswith("An Leitungs"):
            plot_max = max(self.link_dl, max(dl_hist_vals, default=0))
        else:
            plot_max = max(dl_hist_vals, default=0)

        y_max = max(plot_max, 1.0)
        pad_top = y_max * 0.05
        pad_bot = y_max * 0.08

        if is_mirrored:
            self.plot_widget.setYRange(-(y_max + pad_top), y_max + pad_top)
        else:
            self.plot_widget.setYRange(-pad_bot, y_max + pad_top)

    def _get_smoothed_data(self, x, y, clip_negative: bool = True):
        """Apply PChip spline smoothing to a data series.

        Upsamples *y* by a factor of 6 using
        :class:`~scipy.interpolate.PchipInterpolator`.  Returns the original
        arrays unchanged when ``scipy`` is not installed or when fewer than
        four data points are available.

        Parameters
        ----------
        x : np.ndarray
            Sample positions (integer indices).
        y : np.ndarray
            Sample values in Mbit/s.
        clip_negative : bool
            When ``True``, any interpolated value below zero is clamped to
            zero.  Set to ``False`` in mirror-upload mode where negative
            values are intentional (reflected upload curve).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            ``(x_new, y_smooth)`` with higher resolution, or ``(x, y)``
            as a no-op fallback.
        """
        if PchipInterpolator is None or len(x) < 4:
            return x, y
        try:
            interp = PchipInterpolator(x, y)
            x_new = np.linspace(x.min(), x.max(), len(x) * 6)
            y_smooth = interp(x_new)
            if clip_negative:
                y_smooth[y_smooth < 0] = 0.0
            return x_new, y_smooth
        except Exception:
            return x, y

    def _apply_style(self):
        """Update curve pens and fill visibility to match the configured style.

        Compares the current style against :attr:`_current_style` and returns
        immediately when unchanged, avoiding redundant pen-object creation on
        every data frame.

        *Neon-Lines*
            Both curves rendered with a 2-pixel bright pen; fill items hidden.
        *Gefüllte Flächen*
            Curves rendered with a thin 1-pixel outline; fill items visible
            with 50 % alpha brush.
        """
        style = self.cfg.get_style()
        if style == self._current_style:
            return
        self._current_style = style

        if style.startswith("Gefüllte"):
            self.dl_curve.setPen(pg.mkPen(color=C_DL, width=1))
            self.ul_curve.setPen(pg.mkPen(color=C_UL, width=1))
            self._dl_fill.setVisible(True)
            self._ul_fill.setVisible(True)
        else:  # Neon-Lines
            self.dl_curve.setPen(pg.mkPen(color=C_DL, width=2))
            self.ul_curve.setPen(pg.mkPen(color=C_UL, width=2))
            self._dl_fill.setVisible(False)
            self._ul_fill.setVisible(False)

    # ── Aktionen ──────────────────────────────────────────────────────────

    def _open_config(self):
        dlg = ConfigDialog(self.cfg, self)
        if dlg.exec_():
            self.cfg.reload()
            self._current_style = None  # Stil-Cache ungültig machen
            # Hintergrundfarbe sofort anpassen
            bg = C_BG if self.cfg.get_bg() == "schwarz" else "#eff1f5"
            self.plot_widget.setBackground(QColor(bg))
            self._reconnect()

    def _reconnect(self):
        self.statusBar().showMessage("Verbinde neu…", 0)
        self._hist_snapshot = []
        self.dl_curve.clear()
        self.ul_curve.clear()
        self._dl_zero.clear()
        self._ul_zero.clear()
        for card in (self._card_dl, self._card_ul, self._card_peak_dl, self._card_peak_ul):
            card.set_value(-1)
        # Thread-sicherer Aufruf über Signal/Slot (QueuedConnection)
        self._reconnect_signal.emit()

    def _open_discovery_dialog(self):
        dlg = DiscoveryDialog(self)
        dlg.device_selected.connect(self._on_device_selected)
        result = dlg.exec_()
        if result == QDialog.Rejected:
            # Kein Gerät gewählt → Einstellungsdialog öffnen
            cfg_dlg = ConfigDialog(self.cfg, self)
            if cfg_dlg.exec_():
                self.cfg.reload()
                self._current_style = None
                self._reconnect()
            else:
                # Abbrechen: trotzdem mit bestehender Konfiguration nochmal versuchen
                self._reconnect()

    def _on_device_selected(self, device_info):
        """Wird aufgerufen wenn der Nutzer ein Gerät im Discovery-Dialog wählt."""
        self.statusBar().showMessage(f"Verbinde mit {device_info.model} ({device_info.ip})…", 0)
        self._hist_snapshot = []
        self.dl_curve.clear()
        self.ul_curve.clear()
        for card in (self._card_dl, self._card_ul, self._card_peak_dl, self._card_peak_ul):
            card.set_value(-1)
        # IP an Worker übergeben (thread-sicher über Signal)
        self._set_device_signal.emit(device_info)

    def _show_debug_info(self):
        """Öffnet Debug-Dialog. Daten werden asynchron im Worker-Thread geholt."""
        # Platzhalter-Dialog anzeigen, während Worker Daten sammelt
        self._debug_dialog = QDialog(self)
        self._debug_dialog.setWindowTitle("Debug-Informationen")
        self._debug_dialog.resize(680, 500)
        layout = QVBoxLayout(self._debug_dialog)
        self._debug_text = QTextEdit()
        self._debug_text.setReadOnly(True)
        self._debug_text.setFont(QFont("Courier", 9))
        self._debug_text.setPlainText("Daten werden abgerufen…")
        layout.addWidget(self._debug_text)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self._debug_dialog.close)
        layout.addWidget(close_btn)
        self._debug_dialog.show()
        # Daten-Anfrage an Worker senden (läuft im Worker-Thread, blockiert GUI nicht)
        self._debug_request.emit()

    @pyqtSlot(str)
    def _handle_debug_info(self, info: str):
        """Empfängt Debug-Info vom Worker und befüllt den offenen Dialog."""
        if self._debug_dialog and self._debug_dialog.isVisible():
            self._debug_text.setPlainText(info)

    def _show_about(self):
        QMessageBox.about(
            self, "Über FB Speed Monitor",
            f"<b>FB Speed Monitor</b><br>"
            f"Version 5.0<br><br>"
            f"FRITZ!Box-Bandbreitenmonitor mit Auto-Discovery,<br>"
            f"Live-Graph und Cross-Platform-Support.<br><br>"
            f"<small>© 2025 · Apache-2.0 License</small>"
        )

    # ── Fenster-Lifecycle ─────────────────────────────────────────────────

    def save_window_position(self):
        try:
            if "WINDOW" not in self.cfg.config:
                self.cfg.config.add_section("WINDOW")
            self.cfg.config["WINDOW"]["x"] = str(self.pos().x())
            self.cfg.config["WINDOW"]["y"] = str(self.pos().y())
            with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f:
                self.cfg.config.write(f)
        except Exception as e:
            print(f"Fehler beim Speichern der Fensterposition: {e}")

    def _quit_application(self):
        self.save_window_position()
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(3000)
        QApplication.instance().quit()

    def closeEvent(self, event):
        self._quit_application()
        event.accept()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    # Windows DPI-Awareness vor QApplication setzen
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    else:
        os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    if PchipInterpolator is None:
        print("HINWEIS: 'scipy' nicht installiert – Kurvenglättung deaktiviert. (pip install scipy)")

    app = QApplication(sys.argv)
    app.setApplicationName("FB Speed Monitor")
    app.setApplicationVersion("5.0")
    app.setStyle("Fusion")

    # Dark Palette für systemweites Styling (ergänzt den QSS-Stylesheet)
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(C_BG))
    palette.setColor(QPalette.WindowText,      QColor(C_TEXT))
    palette.setColor(QPalette.Base,            QColor(C_SURFACE))
    palette.setColor(QPalette.AlternateBase,   QColor(C_MANTLE))
    palette.setColor(QPalette.ToolTipBase,     QColor(C_SURFACE))
    palette.setColor(QPalette.ToolTipText,     QColor(C_TEXT))
    palette.setColor(QPalette.Text,            QColor(C_TEXT))
    palette.setColor(QPalette.Button,          QColor(C_SURFACE))
    palette.setColor(QPalette.ButtonText,      QColor(C_TEXT))
    palette.setColor(QPalette.BrightText,      QColor(C_ERR))
    palette.setColor(QPalette.Link,            QColor(C_ACCENT))
    palette.setColor(QPalette.Highlight,       QColor(C_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor(C_BG))
    palette.setColor(QPalette.Disabled, QPalette.Text,       QColor(C_OVERLAY))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(C_OVERLAY))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)

    try:
        mw = FritzMain()
        mw.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(
            None, "Kritischer Fehler",
            f"Die Anwendung konnte nicht gestartet werden:\n{e}\n\n{traceback.format_exc()}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
