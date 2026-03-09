# FB Speed Monitor – Architecture & Code Reference

This document describes the internal structure of FB Speed Monitor for
developers who want to understand, extend, or debug the codebase.

---

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [Threading Model](#2-threading-model)
3. [Signal / Slot Map](#3-signal--slot-map)
4. [Module Reference](#4-module-reference)
   - [config.py](#41-configpy)
   - [fritz_discovery.py](#42-fritz_discoverypy)
   - [fritzreader.py](#43-fritzreaderpy)
   - [fritzworker.py](#44-fritzworkerpy)
   - [gui.py](#45-guipy)
5. [Data Flow](#5-data-flow)
6. [Plot Architecture](#6-plot-architecture)
7. [Configuration File Layout](#7-configuration-file-layout)
8. [Known Limitations & Extension Points](#8-known-limitations--extension-points)

---

## 1. Module Overview

```
FB7590Trafficmonitor/
├── config.py            Config reader / typed getter API
├── fritz_discovery.py   SSDP + fallback device discovery
├── fritzreader.py       TR-064 communication, bandwidth measurement
├── fritzworker.py       QObject worker (runs in background QThread)
├── gui.py               All UI: main window, dialogs, widgets
├── config.ini           User settings (auto-created on first run)
└── requirements.txt     Python dependencies
```

Dependency graph (arrows = "imports"):

```
gui.py
  ├── config.py
  ├── fritzworker.py
  │     └── fritzreader.py
  │           └── fritzconnection (third-party)
  └── fritz_discovery.py
        └── fritzconnection (third-party)
```

---

## 2. Threading Model

```
Main Thread (Qt event loop)               Worker Thread (QThread)
────────────────────────────────────      ───────────────────────────────────
FritzMain (QMainWindow)                   FritzWorker (QObject)
  │                                         │
  │  thread.started ──────────────────────► run()
  │                                         │
  │  _reconnect_signal ───────────────────► reconnect()        ← slot
  │  _debug_request ──────────────────────► fetch_debug_info() ← slot
  │  _set_device_signal ──────────────────► set_device_and_reconnect() ← slot
  │                                         │
  │◄─── connection_status(dict) ───────────┤ emitted after connect()
  │◄─── data_updated(dict) ────────────────┤ emitted every timer tick
  │◄─── discovery_needed() ───────────────┤ emitted on first connect fail
  │◄─── debug_info_ready(str) ────────────┤ emitted after fetch_debug_info()
```

**Key design rule:** No method on `FritzWorker` is ever called *directly*
from the GUI thread.  All invocations go through Qt's signal/slot mechanism,
which automatically uses a `QueuedConnection` when sender and receiver live
in different threads.  This makes every worker slot safe to call blocking
network I/O.

---

## 3. Signal / Slot Map

| Signal (source) | Connected slot (target) | Direction |
|-----------------|------------------------|-----------|
| `QThread.started` | `FritzWorker.run` | GUI → Worker |
| `FritzMain._reconnect_signal` | `FritzWorker.reconnect` | GUI → Worker |
| `FritzMain._debug_request` | `FritzWorker.fetch_debug_info` | GUI → Worker |
| `FritzMain._set_device_signal(obj)` | `FritzWorker.set_device_and_reconnect` | GUI → Worker |
| `FritzWorker.connection_status(dict)` | `FritzMain._handle_connection_status` | Worker → GUI |
| `FritzWorker.data_updated(dict)` | `FritzMain._handle_data_update` | Worker → GUI |
| `FritzWorker.discovery_needed()` | `FritzMain._open_discovery_dialog` | Worker → GUI |
| `FritzWorker.debug_info_ready(str)` | `FritzMain._handle_debug_info` | Worker → GUI |
| `_DiscoveryThread.progress(str)` | `DiscoveryDialog._status_label.setText` | Thread → Dialog |
| `_DiscoveryThread.result(list)` | `DiscoveryDialog._on_result` | Thread → Dialog |
| `DiscoveryDialog.device_selected(obj)` | `FritzMain._on_device_selected` | Dialog → Main |

---

## 4. Module Reference

### 4.1 `config.py`

**Class: `Config`**

Thin wrapper around `configparser.ConfigParser`.  Exposes all settings as
typed getter methods with safe fallback values.

| Method | Returns | Fallback |
|--------|---------|---------|
| `get_fritzbox_credentials()` | `(address, username, password)` | – |
| `get_window_position()` | `(x, y)` | `(100, 100)` |
| `get_always_on_top()` | `bool` | `True` |
| `get_refresh_interval()` | `int` seconds | `2` |
| `get_smoothing_enabled()` | `bool` | `False` |
| `get_yaxis_scaling_mode()` | `str` | `"An Leitungskapazität anpassen"` |
| `get_animation_enabled()` | `bool` | `True` |
| `get_bg()` | `"schwarz"` \| `"weiss"` | `"schwarz"` |
| `get_style()` | `"Neon-Lines"` \| `"Gefüllte Flächen"` | `"Neon-Lines"` |
| `get_ulmode()` | `"Überlagert"` \| `"Spiegeln unter 0"` | `"Überlagert"` |
| `reload()` | – | – |

---

### 4.2 `fritz_discovery.py`

**Dataclass: `DeviceInfo`**

```python
@dataclass
class DeviceInfo:
    ip: str
    model: str = "FRITZ!Box"
    tech: str = ""           # e.g. "VDSL2/Supervectoring"
    features: list = []      # e.g. ["supervectoring", "wifi6"]
```

**Function: `discover_devices(progress_cb=None) -> list[DeviceInfo]`**

Blocking discovery function, intended for background threads only.

Algorithm:
1. Send SSDP `M-SEARCH` to `239.255.255.250:1900` (TTL=4, timeout=2.5 s)
   for two service types.  Collect all responding IPs.
2. Append `FALLBACK_IPS` entries not already found.
3. For each candidate IP: attempt `FritzConnection(address, timeout=5.0)`.
   On success, enrich with `MODEL_DB` lookup and append to result list.

**Constant: `MODEL_DB`**

12-entry dict mapping model name prefixes to `(technology, features)`.
Add new entries here to support additional models.

---

### 4.3 `fritzreader.py`

**Class: `FritzReader`**

Manages one TR-064 session and provides bandwidth measurements.

**Constructor variants:**

```python
FritzReader(address, username, password, history_size=360)
FritzReader.from_config(config_obj, history_size=360)
FritzReader.from_device_info(device_info, config_obj, history_size=360)
```

**Bandwidth measurement methods (tried in order):**

| # | Method | TR-064 Action | Notes |
|---|--------|--------------|-------|
| 1 | `_get_bandwidth_addon_infos` | `WANCommonIFC1 / GetAddonInfos` | Returns direct byte rates – preferred |
| 2 | `_get_bandwidth_traffic_stats` | `WANCommonIFC1 / X_AVM-DE_GetOnlineMonitor` | Newer firmware only |
| 3 | `_get_bandwidth_total_bytes` | `GetTotalBytesReceived` + `GetTotalBytesSent` | Always available; requires 2 calls |

A method signals "not available" by returning `(None, None)`.  The next
method is then tried automatically.

**Plausibility filter** (in `get_bandwidth`):

Values exceeding `1.5 × line_capacity` are discarded and replaced by
`history[-1]`.  The ceiling falls back to 2000 Mbit/s when line capacity
could not be read from the router.

**Key attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `history` | `deque(maxlen=360)` | Ring buffer of `(dl, ul)` tuples |
| `max_dl` / `max_ul` | `float` | Session peaks |
| `link_max_dl` / `link_max_ul` | `float` | Line capacity in Mbit/s |
| `fc` | `FritzConnection` \| `None` | Active connection |

---

### 4.4 `fritzworker.py`

**Class: `FritzWorker(QObject)`**

All public slots must be invoked via signals from the GUI (never called
directly across threads).

| Slot | Triggered by | Action |
|------|-------------|--------|
| `run()` | `QThread.started` | Create timer (once), call `_do_connect()` |
| `reconnect()` | `_reconnect_signal` | Stop timer, clear history, `_do_connect()` |
| `set_device_and_reconnect(DeviceInfo)` | `_set_device_signal` | Save IP to config, reconnect |
| `update_data()` | `QTimer.timeout` | Fetch bandwidth, emit `data_updated` |
| `fetch_debug_info()` | `_debug_request` | Call `get_detailed_info()`, emit result |
| `stop()` | Called in `closeEvent` | Set `_is_running=False`, stop timer |

**Important implementation detail – timer lifecycle:**

`QTimer` is created exactly once in `run()` using `if self.timer is None`.
Subsequent `reconnect()` calls stop and restart the *same* timer object,
preventing the memory leak that would occur if a new `QTimer` were created
on every reconnect.

---

### 4.5 `gui.py`

**Colour constants (Catppuccin Mocha):**

| Constant | Hex | Usage |
|----------|-----|-------|
| `C_BG` | `#1e1e2e` | Main background |
| `C_MANTLE` | `#181825` | Menu/status bar |
| `C_SURFACE` | `#313244` | Cards, inputs |
| `C_OVERLAY` | `#585b70` | Borders, grid |
| `C_TEXT` | `#cdd6f4` | Primary text |
| `C_DL` | `#a6e3a1` | Download (green) |
| `C_UL` | `#f38ba8` | Upload (pink/red) |
| `C_ACCENT` | `#89b4fa` | Interactive (blue) |

**Classes:**

| Class | Base | Purpose |
|-------|------|---------|
| `_DiscoveryThread` | `QThread` | Runs `discover_devices()` in background |
| `DiscoveryDialog` | `QDialog` | Device picker shown on first connect fail |
| `MetricCard` | `QFrame` | One-metric display card (value + title + unit) |
| `ConfigDialog` | `QDialog` | Settings form; writes `config.ini` on accept |
| `FritzMain` | `QMainWindow` | Main window; owns worker thread and plot |

**`FritzMain._update_plot()` – critical rendering path:**

```
_hist_snapshot  →  split DL/UL arrays
                →  mirror UL if "Spiegeln unter 0"
                →  optional PChip smoothing (clip_negative aware)
                →  setData() on dl_curve, ul_curve, _dl_zero, _ul_zero
                   └── FillBetweenItem auto-updates via sigPlotChanged
                →  _apply_style()  (pen/fill only on style change)
                →  setYRange()
```

**`_hist_snapshot`** is a `list` copy of the worker's `deque`, created in
`_handle_data_update()`.  The copy is necessary to give the crosshair handler
random-access via `list[index]` without touching the worker's deque from the
GUI thread.

---

## 5. Data Flow

```
FRITZ!Box  ──TR-064──►  FritzReader.get_bandwidth()
                              │
                        (dl, ul, history, peaks)
                              │
                         FritzWorker.update_data()
                              │
                    data_updated signal (dict)
                              │
                    FritzMain._handle_data_update()
                         │           │
                  _hist_snapshot    MetricCards.set_value()
                         │
                  _update_plot()
                         │
                  PlotCurveItem.setData()
                         │
                  FillBetweenItem  ← auto-updates
```

---

## 6. Plot Architecture

### Persistent items (created once in `_setup_plot`)

```
PlotWidget
├── _dl_zero  (PlotCurveItem, pen=None)   ← zero baseline for DL fill
├── _ul_zero  (PlotCurveItem, pen=None)   ← zero baseline for UL fill
├── _dl_fill  (FillBetweenItem: dl_curve ↔ _dl_zero)
├── _ul_fill  (FillBetweenItem: ul_curve ↔ _ul_zero)
├── dl_curve  (PlotCurveItem, name="↓ Download")
├── ul_curve  (PlotCurveItem, name="↑ Upload")
├── _crosshair_v  (InfiniteLine, dashed)
├── _crosshair_label  (TextItem, HTML tooltip)
└── _error_item  (TextItem, shown on connection error)
```

`FillBetweenItem` subscribes to `sigPlotChanged` on both its curve arguments.
Calling `setData()` on `dl_curve` or `_dl_zero` triggers an automatic
redraw of `_dl_fill` – no manual remove/add cycle is needed.

### Style toggling

```python
# Neon-Lines
dl_curve.setPen(mkPen(C_DL, width=2))
_dl_fill.setVisible(False)

# Gefüllte Flächen
dl_curve.setPen(mkPen(C_DL, width=1))
_dl_fill.setVisible(True)
```

Pen objects are only created when `cfg.get_style()` differs from
`_current_style` (cached value updated on each change).

---

## 7. Configuration File Layout

```
config.ini
│
├── [FRITZBOX]
│   ├── address    – IP or hostname
│   ├── username   – login name
│   └── password   – plain-text password
│
├── [WINDOW]
│   ├── x              – last window left edge
│   ├── y              – last window top edge
│   └── always_on_top  – yes | no
│
└── [APP]
    ├── refresh_interval   – integer seconds
    ├── bg                 – schwarz | weiss
    ├── style              – Neon-Lines | Gefüllte Flächen
    ├── ulmode             – Überlagert | Spiegeln unter 0
    ├── smoothing          – yes | no
    ├── animation          – yes | no
    └── yaxis_scaling      – An Leitungskapazität anpassen |
                             Dynamisch an Spitzenwert
```

`CONFIG_PATH` in `config.py` resolves to `<project_dir>/config.ini` using
`Path(__file__).resolve().parent`, which works correctly regardless of the
current working directory.

---

## 8. Known Limitations & Extension Points

### Adding a new FRITZ!Box model

Edit `MODEL_DB` in `fritz_discovery.py`:

```python
"FRITZ!Box XXXX YY": ("Technology string", ["feature1", "feature2"]),
```

The key must be a prefix of the `modelname` string returned by
`FritzConnection.modelname`.

### Supporting a new bandwidth measurement method

Add a new private method to `FritzReader` following the signature
`() -> tuple[float | None, float | None]` and append it to the `methods`
list in `get_bandwidth()`.

### Changing the colour scheme

All colours are defined as module-level constants in `gui.py` (the `C_*`
variables).  Change them there and the entire stylesheet and graph update
automatically because `STYLESHEET` is an f-string evaluated at import time.

### Adding a new settings field

1. Add a getter to `Config` in `config.py`.
2. Add the widget and save logic to `ConfigDialog._init_ui()` /
   `ConfigDialog._apply()` in `gui.py`.
3. Read the value where needed (prefer calling the getter at the start of
   the function rather than on every frame).

### Increasing history depth

Change `history_size=360` in `FritzMain._start_worker()`.  At a 2-second
interval, `history_size=1800` covers 60 minutes.  Note that a longer history
increases the numpy array allocation on every plot update.
