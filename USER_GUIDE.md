# FB Speed Monitor – User Guide

A lightweight desktop application that displays real-time upload and download
rates for your FRITZ!Box router, with a live graph, peak tracking, and
automatic device discovery.

![FB Speed Monitor screenshot](pic/showcase.png)

---

## Table of Contents

1. [Requirements](#1-requirements)
2. [Installation](#2-installation)
   - [Linux](#21-linux)
   - [Windows](#22-windows)
3. [First Start & Auto-Discovery](#3-first-start--auto-discovery)
4. [Manual Configuration](#4-manual-configuration)
5. [User Interface](#5-user-interface)
   - [Metric Cards](#51-metric-cards)
   - [Live Graph](#52-live-graph)
   - [Status Bar & Title](#53-status-bar--title)
6. [Settings Reference](#6-settings-reference)
7. [Menus](#7-menus)
8. [Troubleshooting](#8-troubleshooting)
9. [FRITZ!Box Prerequisites](#9-fritzbox-prerequisites)

---

## 1. Requirements

| Component | Minimum version |
|-----------|----------------|
| Python    | 3.10           |
| PyQt5     | 5.15           |
| pyqtgraph | 0.13           |
| fritzconnection | 1.12    |
| numpy     | 1.24           |
| scipy     | 1.10 *(optional – enables curve smoothing)* |

The application runs on **Linux** and **Windows** without modification.
macOS is not officially tested.

---

## 2. Installation

### 2.1 Linux

```bash
# 1. Clone or download the repository
git clone <repo-url> FB7590Trafficmonitor
cd FB7590Trafficmonitor

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python gui.py
```

### 2.2 Windows

```bat
REM 1. Open a Command Prompt and navigate to the project folder
cd C:\path\to\FB7590Trafficmonitor

REM 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

REM 3. Install dependencies
pip install -r requirements.txt

REM 4. Run
python gui.py
```

> **Tip:** You can double-click `install.bat` to automate steps 2–3 on
> Windows.  Edit the script to adjust the Python executable path if needed.

---

## 3. First Start & Auto-Discovery

When you launch the application for the first time (or when the configured
address is unreachable), the **FRITZ!Box Search** dialog opens automatically.

```
┌─────────────────────────────────────────────────┐
│  FRITZ!Box automatically search                 │
│                                                 │
│  Running SSDP/UPnP discovery …                 │
│  ████░░░░░░░░░░░░░░░░░░  (progress bar)         │
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │  FRITZ!Box 7590 AX – VDSL2/Supervect.  │   │
│  │  [192.168.178.1]                        │   │
│  └─────────────────────────────────────────┘   │
│                                                 │
│  [Connect]  [Search again]  [Configure manually]│
└─────────────────────────────────────────────────┘
```

**Discovery works in two phases:**

1. **SSDP/UPnP multicast** – sends a broadcast to `239.255.255.250:1900` and
   listens for responses from Internet-Gateway devices.
2. **Fallback probe** – if multicast finds nothing, the following addresses are
   tested sequentially: `192.168.178.1`, `192.168.2.1`, `192.168.1.1`,
   `192.168.0.1`, `fritz.box`.

Once a device is found, select it and click **Connect**.  The chosen IP
address is saved to `config.ini` so it is used on all subsequent starts.

If your router is on a non-standard subnet or is reachable only via a VPN
tunnel, click **Configure manually** and enter the address directly.

---

## 4. Manual Configuration

Open *Konfiguration → Einstellungen* (or press `Ctrl+,`) to edit all
settings.  Changes take effect after clicking **Übernehmen**, which saves
`config.ini` and triggers an automatic reconnect.

| Field | Description |
|-------|-------------|
| **FRITZ!Box address** | IP address or hostname (e.g. `192.168.178.1`, `fritz.box`) |
| **Username** | Router login name – leave empty if your box uses only a password |
| **Password** | Router password (stored in plain text in `config.ini`) |
| **Refresh interval** | How often to poll the router (1–60 seconds, default 2 s) |
| **Always on top** | Keep the window floating above all other windows |
| **Background** | `schwarz` (dark) or `weiss` (light) graph background |
| **Curve style** | `Neon-Lines` or `Gefüllte Flächen` (filled areas) |
| **Upload display** | `Überlagert` (overlaid) or `Spiegeln unter 0` (mirrored below zero) |
| **Y-axis scaling** | Fixed to line capacity or dynamic to session peak |
| **Smooth curves** | PChip spline interpolation (requires scipy) |

---

## 5. User Interface

### 5.1 Metric Cards

The four cards at the top of the window show:

| Card | Content |
|------|---------|
| **↓ Download** | Current download rate in Mbit/s |
| **↑ Upload** | Current upload rate in Mbit/s |
| **↓ Peak DL** | Highest download rate seen in the current session |
| **↑ Peak UL** | Highest upload rate seen in the current session |

Peak values are reset whenever the connection is re-established.

### 5.2 Live Graph

The graph plots the last 360 measurements (history depth) on the X-axis.
At the default 2-second refresh interval this covers 12 minutes of history.

**Crosshair:** Move the mouse over the graph to activate a dashed vertical
line.  A tooltip shows the exact download and upload values at the cursor
position.

**Mirror mode:** When *Spiegeln unter 0* is selected, download is plotted
above the zero line and upload below it, making it easy to see simultaneous
traffic at a glance.

**Smoothing:** When scipy is installed and smoothing is enabled, the curves
are upsampled by 6× using a PChip spline, giving a fluid appearance without
distorting the actual measurements.

### 5.3 Status Bar & Title

* **Window title** – shows the detected model name once connected, e.g.
  `FB Speed Monitor – FRITZ!Box 7590 AX`.
* **Info line** (below cards) – shows model, line capacity, and WAN IP.
* **Status bar** (bottom) – displays transient messages such as
  *"Connected"* or *"Reconnecting …"*.

---

## 6. Settings Reference

`config.ini` is a standard Windows INI file stored next to `gui.py`.

```ini
[FRITZBOX]
address  = 192.168.178.1   ; Router IP or hostname
username = admin            ; Leave empty for password-only boxes
password = yourpassword     ; Stored in plain text

[WINDOW]
x            = 100          ; Last horizontal window position (pixels)
y            = 100          ; Last vertical window position (pixels)
always_on_top = yes         ; yes | no

[APP]
refresh_interval = 2        ; Polling interval in seconds (1–60)
bg               = schwarz  ; schwarz | weiss
style            = Neon-Lines          ; Neon-Lines | Gefüllte Flächen
ulmode           = Überlagert          ; Überlagert | Spiegeln unter 0
smoothing        = no                  ; yes | no  (requires scipy)
animation        = yes                 ; yes | no
yaxis_scaling    = An Leitungskapazität anpassen
                             ; An Leitungskapazität anpassen |
                             ; Dynamisch an Spitzenwert
```

> **Security note:** The password is stored in plain text.  On a shared
> machine consider restricting file permissions: `chmod 600 config.ini`.

---

## 7. Menus

### Konfiguration
| Action | Shortcut | Description |
|--------|----------|-------------|
| Einstellungen … | `Ctrl+,` | Open the settings dialog |
| FRITZ!Box suchen … | `Ctrl+F` | Re-run device discovery |
| Neu verbinden | `F5` | Force reconnect with current settings |

### Debug
| Action | Description |
|--------|-------------|
| Debug-Informationen … | Fetches a full TR-064 service dump from the router and displays it in a read-only dialog.  Useful for diagnosing unsupported firmware versions. |

### Hilfe
| Action | Description |
|--------|-------------|
| Über … | Shows application version information |

---

## 8. Troubleshooting

### "Connection to FRITZ!Box failed" on startup

1. Open *Konfiguration → FRITZ!Box suchen* to re-run discovery.
2. If discovery finds nothing, check that your PC is on the same subnet as
   the router.
3. Verify that **UPnP** and/or **TR-064** are enabled on the router
   (see [Section 9](#9-fritzbox-prerequisites)).
4. If the router is behind a VPN tunnel, increase the timeout in the source
   (`fritzreader.py`, `timeout=12.0`) if connections are still timing out.

### Bandwidth always shows 0.0 Mbit/s

* The router may not support the primary measurement method.  Check the
  Debug dialog – if all three action calls show errors, the TR-064 interface
  may be restricted.
* Ensure the configured username has access to the TR-064 API on the router.

### Curve smoothing checkbox is greyed out

`scipy` is not installed in the active Python environment:

```bash
pip install scipy
```

### Window position is off-screen after changing monitor setup

Delete the `[WINDOW]` section from `config.ini` and restart.  The window
will open at the default position (100, 100).

### Tray icon shows "no icon" warning

This is cosmetic.  The application does not bundle an icon file.  Add a
PNG file and reference it in `gui.py:_setup_tray()` to remove the warning.

---

## 9. FRITZ!Box Prerequisites

The application uses the **TR-064** interface (port 49000) over HTTP.  Two
settings must be enabled on the router:

1. Log in to the FRITZ!Box web interface.
2. Navigate to **Home Network → Network → Network Settings**.
3. Enable **"Allow access for applications"** (UPnP).
4. Navigate to **Home Network → Network → Network Settings →
   Advanced settings**.
5. Enable **"Transmit status information of the FRITZ!Box via UPnP"**.

> The application is **read-only** – it never changes any router setting.
