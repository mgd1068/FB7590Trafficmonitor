"""
fritzworker.py
==============
Background worker for FRITZ!Box network communication.

Threading model
---------------
:class:`FritzWorker` is a :class:`~PyQt5.QtCore.QObject` that is moved to a
dedicated :class:`~PyQt5.QtCore.QThread` by the GUI before the thread is
started.  All methods decorated with :func:`~PyQt5.QtCore.pyqtSlot` execute
in the worker thread and are therefore safe to call blocking network I/O
without freezing the user interface.

Cross-thread communication is handled exclusively via Qt signals and slots:

* **Worker → GUI** – :attr:`connection_status`, :attr:`data_updated`,
  :attr:`discovery_needed`, :attr:`debug_info_ready` are emitted from the
  worker thread and delivered to the main thread via Qt's automatic
  *queued connection* mechanism.

* **GUI → Worker** – The GUI defines private signals
  (``_reconnect_signal``, ``_debug_request``, ``_set_device_signal``) that
  are connected to the worker's slots.  Emitting them from the GUI thread
  schedules the corresponding slot call in the worker thread's event loop,
  avoiding any direct cross-thread method calls.

Connection lifecycle
--------------------
``run()`` → ``_do_connect()`` → success → start :class:`QTimer` for
``update_data()`` polls.

On failure during the *first* start, :attr:`discovery_needed` is emitted so
the GUI can open the auto-discovery dialog.  On failure during a subsequent
reconnect, only :attr:`connection_status` is emitted (no dialog).
"""

from pathlib import Path
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from fritzreader import FritzReader


class FritzWorker(QObject):
    """Encapsulates all blocking FRITZ!Box communication.

    Instances must be moved to a :class:`~PyQt5.QtCore.QThread` before
    :meth:`run` is called::

        thread = QThread()
        worker = FritzWorker(cfg)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.start()

    Parameters
    ----------
    cfg : config.Config
        Application configuration.  Credentials and timing settings are
        read from this object at connection time.
    """

    # ------------------------------------------------------------------
    # Signals emitted by the worker (received in the GUI thread)
    # ------------------------------------------------------------------

    #: Emitted once after every (re-)connect attempt.
    #: ``dict`` keys: ``"connected"`` (bool), ``"message"`` (str),
    #: ``"details"`` (dict with ``link_dl``, ``link_ul``, ``wan_ip``,
    #: ``model``) or ``None`` on failure.
    connection_status = pyqtSignal(dict)

    #: Emitted on every successful timer tick with fresh bandwidth data.
    #: ``dict`` keys: ``"down"``, ``"up"``, ``"max_dl"``, ``"max_ul"``
    #: (all ``float``), ``"history"`` (deque), ``"error"`` (``None`` or str).
    data_updated = pyqtSignal(dict)

    #: Emitted when the very first connection attempt fails.
    #: The GUI connects this to ``_open_discovery_dialog()``.
    discovery_needed = pyqtSignal()

    #: Emitted in response to :meth:`fetch_debug_info` with the full
    #: diagnostic text from :meth:`~fritzreader.FritzReader.get_detailed_info`.
    debug_info_ready = pyqtSignal(str)

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, cfg) -> None:
        super().__init__()
        self.cfg = cfg

        #: Active :class:`~fritzreader.FritzReader`, created in :meth:`_do_connect`.
        self.reader: FritzReader | None = None

        #: :class:`~PyQt5.QtCore.QTimer` created exactly once in :meth:`run`.
        #: Stored as an instance attribute to avoid the timer being garbage-collected.
        self.timer: QTimer | None = None

        self._is_running: bool = True
        self._first_run: bool = True  # Guards the one-time discovery_needed emit

        #: Holds a :class:`~fritz_discovery.DeviceInfo` passed from the discovery
        #: dialog.  Consumed by the next :meth:`_do_connect` call and then cleared.
        self._pending_device_info = None

    # ------------------------------------------------------------------
    # Slots (executed in the worker thread)
    # ------------------------------------------------------------------

    @pyqtSlot()
    def run(self) -> None:
        """Initial entry point – called when the worker thread starts.

        Creates the :class:`~PyQt5.QtCore.QTimer` exactly once (guard via
        ``if self.timer is None``), then delegates to :meth:`_do_connect`.
        The single-creation guard prevents a timer leak on subsequent
        :meth:`reconnect` calls, which reuse this same timer instance.
        """
        if self.timer is None:
            self.timer = QTimer()
            self.timer.timeout.connect(self.update_data)
        self._do_connect()

    @pyqtSlot()
    def reconnect(self) -> None:
        """Reset history and peaks, then attempt a fresh connection.

        Called from the GUI via the ``_reconnect_signal`` (queued connection)
        so that execution happens inside the worker thread's event loop,
        making the blocking network call thread-safe.
        """
        if self.timer:
            self.timer.stop()
        if self.reader:
            self.reader.history.clear()
            self.reader.reset_maxima()
        self._do_connect()

    @pyqtSlot(object)
    def set_device_and_reconnect(self, device_info) -> None:
        """Store a device selected in the discovery dialog and reconnect.

        Persists the chosen IP address to ``config.ini`` so it survives
        application restarts, then calls :meth:`reconnect`.

        Parameters
        ----------
        device_info : fritz_discovery.DeviceInfo
            Device chosen by the user in :class:`~gui.DiscoveryDialog`.
        """
        self._pending_device_info = device_info

        # Persist the new address to config.ini
        if "FRITZBOX" not in self.cfg.config:
            self.cfg.config.add_section("FRITZBOX")
        self.cfg.config["FRITZBOX"]["address"] = device_info.ip
        try:
            with (Path(__file__).parent / "config.ini").open("w", encoding="utf-8") as f:
                self.cfg.config.write(f)
        except Exception as e:
            print(f"[Worker] Failed to persist IP to config: {e}")

        self.reconnect()

    @pyqtSlot()
    def update_data(self) -> None:
        """Timer callback – fetch current bandwidth and emit :attr:`data_updated`.

        On failure, emits ``data_updated`` with ``"error"`` set, then
        attempts an immediate reconnect.  If the reconnect succeeds the
        normal polling cycle continues on the next timer tick.
        """
        if not self._is_running:
            if self.timer:
                self.timer.stop()
            return

        try:
            down, up = self.reader.get_bandwidth()
            if down is None or up is None:
                raise ConnectionError("Invalid data received from FRITZ!Box")

            self.data_updated.emit({
                "down": down,
                "up": up,
                "max_dl": self.reader.max_dl,
                "max_ul": self.reader.max_ul,
                "history": self.reader.history,
                "error": None,
            })

        except Exception as e:
            print(f"[Worker] Data fetch error: {e}")
            self.data_updated.emit({"error": str(e)})
            if not self.reader.connect():
                print("[Worker] Reconnect failed.")
            else:
                print("[Worker] Reconnect successful.")

    @pyqtSlot()
    def fetch_debug_info(self) -> None:
        """Collect verbose diagnostic data and emit :attr:`debug_info_ready`.

        Runs in the worker thread so the potentially slow TR-064 queries do
        not block the GUI.  The GUI opens the debug dialog first, then
        triggers this slot and updates the dialog text when the signal
        arrives.
        """
        if self.reader:
            info = self.reader.get_detailed_info()
        else:
            info = "Not connected."
        self.debug_info_ready.emit(info)

    @pyqtSlot()
    def stop(self) -> None:
        """Stop polling and prevent any further timer callbacks."""
        self._is_running = False
        if self.timer:
            self.timer.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_connect(self) -> None:
        """Build a :class:`~fritzreader.FritzReader` and attempt to connect.

        If :attr:`_pending_device_info` is set (from the discovery dialog)
        the reader is built with that IP; otherwise the stored config
        credentials are used.

        On success, starts the polling timer and emits
        :attr:`connection_status` with ``"connected": True``.
        On failure, emits :attr:`connection_status` with ``"connected": False``
        and – on the very first attempt – also emits :attr:`discovery_needed`.
        """
        if self._pending_device_info:
            self.reader = FritzReader.from_device_info(self._pending_device_info, self.cfg)
            self._pending_device_info = None
        else:
            self.reader = FritzReader.from_config(self.cfg)

        if self.reader.connect():
            self._first_run = False
            self.connection_status.emit({
                "connected": True,
                "message": "Connected",
                "details": {
                    "link_dl": self.reader.link_max_dl,
                    "link_ul": self.reader.link_max_ul,
                    "wan_ip": self.reader.get_ip_addresses()[1],
                    "model": self.reader.fc.modelname if self.reader.fc else "",
                },
            })
            if self.timer:
                self.timer.start(self.cfg.get_refresh_interval() * 1000)
        else:
            self.connection_status.emit({
                "connected": False,
                "message": "Connection to FRITZ!Box failed",
                "details": None,
            })
            if self._first_run:
                # Offer auto-discovery only on the very first failed attempt
                self._first_run = False
                self.discovery_needed.emit()
