"""
config.py
=========
Configuration management for FB Speed Monitor.

Reads and exposes all application settings from ``config.ini`` via typed
getter methods.  The underlying :class:`configparser.ConfigParser` instance
is kept as a public attribute (``self.config``) so that other modules can
write to it directly when saving settings.

Config file sections
--------------------
``[FRITZBOX]``
    Connection credentials for the router.
``[WINDOW]``
    Last known window position and *always-on-top* flag.
``[APP]``
    All visual and behavioural settings (refresh rate, theme, graph style …).
"""

import configparser
from pathlib import Path

#: Absolute path to the INI file, located next to this module.
CONFIG_PATH = Path(__file__).resolve().parent / "config.ini"


class Config:
    """Thin wrapper around :class:`configparser.ConfigParser`.

    Provides typed getter methods for every setting used by the application.
    All getters supply sensible fallback values so the app can still start
    even when a key is missing from the file (e.g. after a manual edit).

    Raises
    ------
    FileNotFoundError
        If ``config.ini`` does not exist when the object is constructed.
        The GUI catches this and creates a default file before retrying.
    """

    def __init__(self) -> None:
        self.config = configparser.ConfigParser()
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"config.ini not found at: {CONFIG_PATH}")
        self.config.read(str(CONFIG_PATH), encoding="utf-8")

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read the INI file from disk.

        Called after the settings dialog saves new values so that the
        in-memory state stays consistent with the file.
        """
        self.config.read(str(CONFIG_PATH), encoding="utf-8")

    # ------------------------------------------------------------------
    # [FRITZBOX] section
    # ------------------------------------------------------------------

    def get_fritzbox_credentials(self) -> tuple:
        """Return ``(address, username, password)`` from ``[FRITZBOX]``.

        Returns
        -------
        tuple[str, str, str]
            IP address or hostname, login name, and password.  Any value
            may be ``None`` if the key is absent in the file.
        """
        section = self.config["FRITZBOX"]
        return section.get("address"), section.get("username"), section.get("password")

    # ------------------------------------------------------------------
    # [WINDOW] section
    # ------------------------------------------------------------------

    def get_window_position(self) -> tuple:
        """Return the last saved ``(x, y)`` window position in screen pixels."""
        section = self.config["WINDOW"]
        return int(section.get("x", 100)), int(section.get("y", 100))

    def get_always_on_top(self) -> bool:
        """Return ``True`` when the window should float above other windows."""
        return self.config.getboolean("WINDOW", "always_on_top", fallback=True)

    # ------------------------------------------------------------------
    # [APP] section
    # ------------------------------------------------------------------

    def get_refresh_interval(self) -> int:
        """Return the polling interval in **seconds** (default: 2)."""
        return int(self.config.get("APP", "refresh_interval", fallback=2))

    def get_smoothing_enabled(self) -> bool:
        """Return ``True`` when PChip curve smoothing is active.

        Smoothing requires ``scipy`` to be installed.  The settings dialog
        disables the checkbox automatically when scipy is unavailable.
        """
        return self.config.getboolean("APP", "smoothing", fallback=False)

    def get_yaxis_scaling_mode(self) -> str:
        """Return the Y-axis scaling strategy.

        Returns
        -------
        str
            ``"An Leitungskapazität anpassen"`` – upper bound is the line
            capacity reported by the router, or
            ``"Dynamisch an Spitzenwert"`` – upper bound follows the session
            peak value.
        """
        return self.config.get(
            "APP", "yaxis_scaling", fallback="An Leitungskapazität anpassen"
        )

    def get_animation_enabled(self) -> bool:
        """Return ``True`` when UI transition animations are active."""
        return self.config.getboolean("APP", "animation", fallback=True)

    def get_bg(self) -> str:
        """Return the plot background setting: ``"schwarz"`` or ``"weiss"``."""
        return self.config.get("APP", "bg", fallback="schwarz")

    def get_style(self) -> str:
        """Return the curve rendering style.

        Returns
        -------
        str
            ``"Neon-Lines"`` for bright lines without fill, or
            ``"Gefüllte Flächen"`` for semi-transparent filled areas.
        """
        return self.config.get("APP", "style", fallback="Neon-Lines")

    def get_ulmode(self) -> str:
        """Return the upload display mode.

        Returns
        -------
        str
            ``"Überlagert"`` – upload curve overlaid on the download axis, or
            ``"Spiegeln unter 0"`` – upload mirrored below the zero line.
        """
        return self.config.get("APP", "ulmode", fallback="Überlagert")
