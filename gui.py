# gui.py
"""
FB Speed – PyQt‑Desktop‑Monitor für FRITZ!Box‑Bandbreite
Version 4.6 - README-Integration und Abschluss
"""
import sys
import traceback
from pathlib import Path
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, QThread
from PyQt5.QtGui import QColor, QIcon, QPalette, QFont
from PyQt5.QtWidgets import (
    QAction, QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMenu, QMenuBar, QPushButton, QSystemTrayIcon,
    QTextEdit, QVBoxLayout, QWidget, QMessageBox, QCheckBox, QSpinBox)

from config import Config
from fritzworker import FritzWorker
try:
    from scipy.interpolate import PchipInterpolator
except ImportError:
    PchipInterpolator = None

DL_COLOR = "#90ee90"
UL_COLOR = "#ffb6c1"

class ConfigDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("FB Speed – Einstellungen")
        self.setModal(True)
        self.setFixedSize(400, 410)
        self._init_ui()

    def _init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)
        try: addr, usr, pwd = self.cfg.get_fritzbox_credentials()
        except Exception: addr, usr, pwd = "192.168.2.1", "", ""
        self.address_edit = QLineEdit(addr or "192.168.2.1")
        self.user_edit = QLineEdit(usr or "")
        self.pass_edit = QLineEdit(pwd or ""); self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addRow("FB-Adresse:", self.address_edit)
        layout.addRow("Benutzer:", self.user_edit)
        layout.addRow("Passwort:", self.pass_edit)
        self.refresh_spin = QSpinBox(); self.refresh_spin.setRange(1, 60); self.refresh_spin.setValue(self.cfg.get_refresh_interval()); self.refresh_spin.setSuffix(" Sekunden")
        layout.addRow("Aktualisierung:", self.refresh_spin)
        self.always_top_check = QCheckBox(); self.always_top_check.setChecked(self.cfg.get_always_on_top())
        layout.addRow("Immer im Vordergrund:", self.always_top_check)
        self.bg_combo = QComboBox(); self.bg_combo.addItems(["schwarz", "weiss"]); self.bg_combo.setCurrentText(self.cfg.config.get("APP", "bg", fallback="schwarz"))
        layout.addRow("Hintergrund:", self.bg_combo)
        self.style_combo = QComboBox(); self.style_combo.addItems(["Neon-Lines", "Gefüllte Flächen"]); self.style_combo.setCurrentText(self.cfg.config.get("APP", "style", fallback="Neon-Lines"))
        layout.addRow("Kurven‑Stil:", self.style_combo)
        self.ulmode_combo = QComboBox(); self.ulmode_combo.addItems(["Überlagert", "Spiegeln unter 0"]); self.ulmode_combo.setCurrentText(self.cfg.config.get("APP", "ulmode", fallback="Überlagert"))
        layout.addRow("Upload‑Anzeige:", self.ulmode_combo)
        self.yaxis_combo = QComboBox(); self.yaxis_combo.addItems(["An Leitungskapazität anpassen", "Dynamisch an Spitzenwert"]); self.yaxis_combo.setCurrentText(self.cfg.get_yaxis_scaling_mode())
        layout.addRow("Y-Achsen-Skalierung:", self.yaxis_combo)
        self.smoothing_check = QCheckBox(); self.smoothing_check.setChecked(self.cfg.config.getboolean("APP", "smoothing", fallback=False))
        if PchipInterpolator is None:
            self.smoothing_check.setEnabled(False)
            self.smoothing_check.setToolTip("Für diese Funktion muss 'scipy' installiert sein (pip install scipy)")
        layout.addRow("Kurven glätten:", self.smoothing_check)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Übernehmen"); cancel_btn = QPushButton("Abbrechen")
        ok_btn.clicked.connect(self._apply); cancel_btn.clicked.connect(self.reject)
        btn_box.addStretch(); btn_box.addWidget(ok_btn); btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)

    def _apply(self):
        for section in ["FRITZBOX", "WINDOW", "APP"]:
            if section not in self.cfg.config: self.cfg.config.add_section(section)
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
        with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f:
            self.cfg.config.write(f)
        QMessageBox.information(self, "Erfolg", "Konfiguration gespeichert! Die Änderungen werden beim nächsten Verbindungsaufbau wirksam.")
        self.accept()

class FritzMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.history = deque(maxlen=360)
        self.link_dl, self.link_ul = 0.0, 0.0
        
        try:
            self._init_config()
            self._init_ui()
            self._start_worker()
        except Exception as e:
            QMessageBox.critical(self, "Initialisierungsfehler", f"Fehler beim Starten der Anwendung:\n{str(e)}\n\n{traceback.format_exc()}")
            sys.exit(1)

    def _init_config(self):
        config_file = Path(__file__).parent / "config.ini"
        if not config_file.exists():
            QMessageBox.warning(self, "Konfiguration", "Keine config.ini gefunden. Eine neue Datei wird mit Standardwerten erstellt.")
            self._create_default_config()
        self.cfg = Config()

    def _create_default_config(self):
        default_config = """[FRITZBOX]
address = 192.168.178.1
username = 
password = 
[WINDOW]
x = 100
y = 100
always_on_top = yes
[APP]
refresh_interval = 2
bg = schwarz
style = Neon-Lines
ulmode = Überlagert
smoothing = no
yaxis_scaling = An Leitungskapazität anpassen
"""
        with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f: f.write(default_config)

    def _init_ui(self):
        self.setWindowTitle("FB Speed Monitor"); self.setWindowIcon(QIcon())
        self._create_menubar()
        container = QWidget(self); self.setCentralWidget(container)
        vbox = QVBoxLayout(container)
        self.main_label = QLabel("Verbinde...", alignment=Qt.AlignCenter); self.main_label.setFont(QFont("Arial", 14, QFont.Bold))
        vbox.addWidget(self.main_label)
        self.minmax_label = QLabel("Maximalwerte: Warten auf Daten...", alignment=Qt.AlignCenter); self.minmax_label.setFont(QFont("Arial", 10))
        vbox.addWidget(self.minmax_label)
        self.ip_label = QLabel("Leitung: Warten auf Daten...", alignment=Qt.AlignCenter); self.ip_label.setFont(QFont("Arial", 9)); self.ip_label.setStyleSheet("color: #aaa;")
        vbox.addWidget(self.ip_label)
        self.plot_widget = pg.PlotWidget(); vbox.addWidget(self.plot_widget)
        self._setup_plot(); self._setup_tray(); self._setup_window_geometry()

    def _create_menubar(self):
        mbar = QMenuBar(self); mbar.setNativeMenuBar(False)
        cfg_menu = mbar.addMenu("&Konfiguration"); act_cfg = QAction("&Einstellungen...", self); act_cfg.setShortcut("Ctrl+,"); act_cfg.triggered.connect(self._open_config); cfg_menu.addAction(act_cfg)
        cfg_menu.addSeparator(); act_reconnect = QAction("&Neu verbinden", self); act_reconnect.setShortcut("F5"); act_reconnect.triggered.connect(self._reconnect); cfg_menu.addAction(act_reconnect)
        debug_menu = mbar.addMenu("&Debug"); act_debug = QAction("&Debug-Informationen...", self); act_debug.triggered.connect(self._show_debug_info); debug_menu.addAction(act_debug)
        help_menu = mbar.addMenu("&Hilfe")
        act_info = QAction("&Info (README)...", self)
        act_info.triggered.connect(self._show_readme_info)
        help_menu.addAction(act_info)
        help_menu.addSeparator()
        act_about = QAction("&Über...", self); act_about.triggered.connect(self._show_about); help_menu.addAction(act_about)
        self.setMenuBar(mbar)

    def _setup_plot(self):
        bg_color_str = self.cfg.config.get("APP", "bg", fallback="schwarz"); self.plot_widget.setBackground('k' if bg_color_str == 'schwarz' else 'w')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("left", "Bandbreite (Mbit/s)"); self.plot_widget.setLabel("bottom", "Zeit (s)")
        self.dl_curve = self.plot_widget.plot(pen=pg.mkPen(color='#00ff00', width=2), name='Download')
        self.ul_curve = self.plot_widget.plot(pen=pg.mkPen(color='#ff4444', width=2), name='Upload')
        self.dl_fill = None; self.ul_fill = None; self.plot_widget.addLegend()
        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('gray', style=Qt.DashLine))
        self.crosshair_label = pg.TextItem(anchor=(0, 1))
        self.plot_widget.addItem(self.crosshair_v, ignoreBounds=True)
        self.plot_widget.addItem(self.crosshair_label, ignoreBounds=True)
        self.plot_proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved, rateLimit=60, slot=self._mouse_moved)
        self.error_text_item = pg.TextItem("", color=(255, 0, 0), anchor=(0.5, 0.5)); self.error_text_item.setFont(QFont("Arial", 16, QFont.Bold)); self.plot_widget.addItem(self.error_text_item); self.error_text_item.hide()

    def _setup_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(), self); tmenu = QMenu()
            show_action = tmenu.addAction("Anzeigen"); show_action.triggered.connect(self.showNormal); show_action.triggered.connect(self.raise_)
            tmenu.addSeparator(); quit_action = tmenu.addAction("Beenden"); quit_action.triggered.connect(self._quit_application)
            self.tray.setContextMenu(tmenu); self.tray.setToolTip("FB Speed Monitor"); self.tray.show()
            self.tray.activated.connect(self._tray_activated)
            
    def _setup_window_geometry(self):
        try:
            self.resize(800, 500)
            x, y = self.cfg.get_window_position()
            self.move(x, y)
            if self.cfg.get_always_on_top():
                self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        except Exception as e:
            self.resize(800, 500)
            print(f"Fehler bei Fenster-Setup: {e}")

    def _start_worker(self):
        self.thread = QThread()
        self.worker = FritzWorker(self.cfg)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.connection_status.connect(self._handle_connection_status)
        self.worker.data_updated.connect(self._handle_data_update)
        self.thread.start()

    def _handle_connection_status(self, status):
        self.statusBar().showMessage(status['message'], 3000)
        if status['connected']:
            details = status['details']
            self.link_dl, self.link_ul = details['link_dl'], details['link_ul']
            wan_ip = details['wan_ip']
            if self.link_dl > 0:
                ip_text = (f"Leitung: <b>↓</b> <font color='{DL_COLOR}'>{self.link_dl:.2f}</font> / "
                           f"<b>↑</b> <font color='{UL_COLOR}'>{self.link_ul:.2f}</font> Mbit/s | WAN-IP: {wan_ip}")
                self.ip_label.setText(ip_text)
            else:
                self.ip_label.setText(f"WAN-IP: {wan_ip}")
        else:
            self.ip_label.setText("Verbindung zur FB fehlgeschlagen")
            if status.get('first_run', False):
                self._open_config()

    def _handle_data_update(self, data):
        if data.get('error'):
            self.error_text_item.setText("Verbindungsproblem!")
            self.error_text_item.setPos(self.plot_widget.width()/2, self.plot_widget.height()/2)
            self.error_text_item.show()
            return
            
        self.error_text_item.hide()
        down, up = data['down'], data['up']
        max_dl, max_ul = data['max_dl'], data['max_ul']
        self.history = data['history']

        main_text = (f"<b>↓</b> <font color='{DL_COLOR}'>{down:.2f}</font> Mbit/s &nbsp;&nbsp;&nbsp;&nbsp; "
                     f"<b>↑</b> <font color='{UL_COLOR}'>{up:.2f}</font> Mbit/s")
        self.main_label.setText(main_text)
        
        minmax_text = (f"Maximalwerte: <b>↓</b> <font color='{DL_COLOR}'>{max_dl:.2f}</font> / "
                       f"<b>↑</b> <font color='{UL_COLOR}'>{max_ul:.2f}</font> Mbit/s")
        self.minmax_label.setText(minmax_text)

        if hasattr(self, 'tray'):
            self.tray.setToolTip(f"FB Speed\n↓ {down:.2f} Mbit/s ↑ {up:.2f} Mbit/s")
        
        self._update_plot()
    
    def _mouse_moved(self, event):
        if not self.history: return
        pos = event[0]
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_widget.getViewBox().mapSceneToView(pos)
            index = int(mouse_point.x())
            if 0 <= index < len(self.history):
                dl, ul = self.history[index]
                self.crosshair_v.setPos(mouse_point.x())
                self.crosshair_label.setHtml(f"<div style='background-color: #555; color: white; padding: 5px; border-radius: 3px;'>↓ {dl:.2f}<br>↑ {ul:.2f}</div>")
                self.crosshair_label.setPos(mouse_point.x(), mouse_point.y())

    def _update_plot(self):
        if self.dl_curve is None or not self.history: return
        dl_history, ul_history = zip(*self.history)
        
        smoothing_enabled = self.cfg.get_smoothing_enabled()
        ulmode = self.cfg.config.get("APP", "ulmode", fallback="Überlagert")
        style = self.cfg.config.get("APP", "style", fallback="Neon-Lines")
        
        x_base = np.arange(len(dl_history))
        dl_y = np.array(dl_history)
        ul_y = np.array([-v for v in ul_history]) if ulmode.startswith("Spiegel") else np.array(ul_history)

        dl_x_plot, dl_y_plot = (self._get_smoothed_data(x_base, dl_y) if smoothing_enabled else (x_base, dl_y))
        ul_x_plot, ul_y_plot = (self._get_smoothed_data(x_base, ul_y) if smoothing_enabled else (x_base, ul_y))

        if style.startswith("Gefüllte"): self.dl_curve.setPen(None); self.ul_curve.setPen(None)
        else: self.dl_curve.setPen(pg.mkPen(color='#00ff00', width=2)); self.ul_curve.setPen(pg.mkPen(color='#ff4444', width=2))
        
        self.dl_curve.setData(dl_x_plot, dl_y_plot)
        self.ul_curve.setData(ul_x_plot, ul_y_plot)
        self._update_fill_areas(style)

        scaling_mode = self.cfg.get_yaxis_scaling_mode()
        plot_max = 0
        if scaling_mode == 'An Leitungskapazität anpassen':
            plot_max = max(self.link_dl, max(dl_history) if dl_history else 0)
        else:
            plot_max = max(dl_history) if dl_history else 0
        
        y_max_range = 10 if plot_max < 10 else plot_max
        padding_top = y_max_range * 0.05
        padding_bottom = y_max_range * 0.1
        
        if ulmode.startswith("Spiegel"):
            self.plot_widget.setYRange(-(y_max_range + padding_top), y_max_range + padding_top)
        else:
            self.plot_widget.setYRange(-padding_bottom, y_max_range + padding_top)

    def _get_smoothed_data(self, x, y):
        if PchipInterpolator is None or len(x) < 4: return x, y
        try:
            interpolator = PchipInterpolator(x, y)
            x_new = np.linspace(x.min(), x.max(), len(x) * 8); y_smooth = interpolator(x_new); y_smooth[y_smooth < 0] = 0
            return x_new, y_smooth
        except Exception: return x, y
    
    def _update_fill_areas(self, style):
        try:
            if self.dl_fill: self.plot_widget.removeItem(self.dl_fill); self.dl_fill = None
            if self.ul_fill: self.plot_widget.removeItem(self.ul_fill); self.ul_fill = None
            if style.startswith("Gefüllte"):
                dl_x, dl_y = self.dl_curve.getData(); ul_x, ul_y = self.ul_curve.getData()
                if dl_x is None or len(dl_x) == 0: return
                x_common = np.unique(np.concatenate((dl_x, ul_x)))
                dl_y_interp = np.interp(x_common, dl_x, dl_y); ul_y_interp = np.interp(x_common, ul_x, ul_y)
                fill_dl_curve = pg.PlotCurveItem(x_common, dl_y_interp, pen=None); fill_ul_curve = pg.PlotCurveItem(x_common, ul_y_interp, pen=None)
                zero_line = pg.PlotCurveItem(x_common, np.zeros_like(x_common), pen=None)
                self.dl_fill = pg.FillBetweenItem(fill_dl_curve, zero_line, brush=pg.mkBrush(0, 255, 0, 60))
                self.ul_fill = pg.FillBetweenItem(fill_ul_curve, zero_line, brush=pg.mkBrush(255, 68, 68, 60))
                self.plot_widget.addItem(self.dl_fill); self.plot_widget.addItem(self.ul_fill)
        except Exception as e: print(f"Fehler bei Fill-Areas: {e}")

    def _open_config(self):
        dlg = ConfigDialog(self.cfg, self)
        if dlg.exec_():
            self.cfg.reload()
            self._reconnect()

    def _reconnect(self):
        self.statusBar().showMessage("Verbinde neu...")
        self.history.clear()
        if self.dl_curve: self.dl_curve.clear()
        if self.ul_curve: self.ul_curve.clear()
        self.worker.reconnect()
    
    def _quit_application(self):
        self.save_window_position()
        self.worker.stop()
        self.thread.quit()
        self.thread.wait()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self._quit_application()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isVisible(): self.hide()
            else: self.showNormal(); self.raise_(); self.activateWindow()

    def save_window_position(self):
        try:
            if "WINDOW" not in self.cfg.config: self.cfg.config.add_section("WINDOW")
            self.cfg.config["WINDOW"]["x"] = str(self.pos().x()); self.cfg.config["WINDOW"]["y"] = str(self.pos().y())
            with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f: self.cfg.config.write(f)
        except Exception as e: print(f"Fehler beim Speichern der Fensterposition: {e}")

    def _show_readme_info(self):
        readme_path = Path(__file__).parent / "README.md"
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_content = f.read()
        except FileNotFoundError:
            readme_content = "Fehler: README.md konnte nicht gefunden werden."

        info_dialog = QDialog(self)
        info_dialog.setWindowTitle("Info / README")
        info_dialog.resize(700, 550)

        layout = QVBoxLayout(info_dialog)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(readme_content)
        text_edit.setFont(QFont("Courier", 9))
        
        layout.addWidget(text_edit)
        
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(info_dialog.close)
        layout.addWidget(close_btn)
        
        info_dialog.exec_()

    def _show_about(self):
        QMessageBox.about(self, "Über FB Speed", "FB Speed Monitor v4.6\n\n© 2025")

    def _show_debug_info(self):
        QMessageBox.information(self, "Debug", "Diese Funktion muss an die neue Thread-Architektur angepasst werden.")

def main():
    if PchipInterpolator is None: print("HINWEIS: 'scipy' ist nicht installiert. Die Kurvenglättung ist deaktiviert. (pip install scipy)")
    app = QApplication(sys.argv)
    app.setApplicationName("FB Speed Monitor")
    app.setApplicationVersion("4.6")
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, QColor(0, 0, 0))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)
    
    try:
        mw = FritzMain()
        mw.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(None, "Kritischer Fehler", f"Die Anwendung konnte nicht gestartet werden:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()