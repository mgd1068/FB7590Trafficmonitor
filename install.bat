
@echo off
setlocal

:: ============================================================================
:: Installer für FB Speed Monitor v1.0
:: ============================================================================
:: Dieses Skript:
:: 1. Prüft auf Administratorrechte und fordert diese an.
:: 2. Prüft, ob Python installiert ist und im PATH verfügbar ist.
:: 3. Fragt den Benutzer nach einem Installationsverzeichnis.
:: 4. Erstellt ein sauberes, isoliertes Python Virtual Environment.
:: 5. Installiert alle notwendigen Pakete aus requirements.txt.
:: 6. Kopiert die Anwendungsdateien.
:: 7. Erstellt eine Desktop-Verknüpfung.
:: 8. Zeigt die README-Datei an.
:: ============================================================================

title FB Speed Monitor - Installer

:: --- 1. Administratorrechte prüfen und anfordern ---
echo Pruefe auf Administratorrechte...
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo Fordere Administratorrechte an...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    if exist "%temp%\getadmin.vbs" ( del "%temp%\getadmin.vbs" )
    pushd "%CD%"
    CD /D "%~dp0"


:: --- 2. Python-Installation prüfen ---
echo.
echo ======================================================
echo 2. Pruefe auf Python-Installation...
echo ======================================================
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo FEHLER: Python scheint nicht installiert zu sein oder ist nicht im System-PATH.
    echo.
    echo Dieses Programm benoetigt Python. Der Installer kann Python aus Sicherheits-
    echo und Transparenzgruenden nicht automatisch installieren.
    echo.
    echo Gleich oeffnet sich die offizielle Python-Download-Seite im Browser.
    echo Bitte laden Sie die neueste Version herunter und installieren Sie sie.
    echo WICHTIG: Setzen Sie beim Installieren den Haken bei "Add Python to PATH".
    echo.
    pause
    start "" "https://www.python.org/downloads/windows/"
    echo.
    echo Bitte starten Sie dieses Skript erneut, nachdem Python installiert wurde.
    goto :eof
) else (
    echo Python-Installation gefunden!
)


:: --- 3. Installationsverzeichnis abfragen ---
echo.
echo ======================================================
echo 3. Installationsverzeichnis waehlen
echo ======================================================
set "default_dir=C:\Program Files\FBSM"
set "install_dir="
set /p install_dir="Bitte geben Sie das Installationsverzeichnis an (Enter fuer '%default_dir%'): "
if not defined install_dir (
    set "install_dir=%default_dir%"
)
if not exist "%install_dir%" (
    mkdir "%install_dir%"
    echo Verzeichnis erstellt: %install_dir%
)


:: --- 4. Python Virtual Environment erstellen ---
echo.
echo ======================================================
echo 4. Erstelle saubere Python-Umgebung (venv)...
echo ======================================================
py -m venv "%install_dir%\venv"
if %errorlevel% neq 0 (
    echo FEHLER: Konnte die virtuelle Umgebung nicht erstellen.
    goto :error
)


:: --- 5. Pakete aus requirements.txt installieren ---
echo.
echo ======================================================
echo 5. Installiere notwendige Pakete...
echo ======================================================
call "%install_dir%\venv\Scripts\activate.bat"
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo FEHLER: Installation der Pakete fehlgeschlagen.
    goto :error
)


:: --- 6. Anwendungsdateien kopieren ---
echo.
echo ======================================================
echo 6. Kopiere Anwendungsdateien...
echo ======================================================
xcopy . "%install_dir%" /E /I /Y /Q
if %errorlevel% neq 0 (
    echo FEHLER: Kopieren der Dateien fehlgeschlagen.
    goto :error
)


:: --- 7. Desktop-Verknüpfung erstellen ---
echo.
echo ======================================================
echo 7. Erstelle Desktop-Verknuepfung...
echo ======================================================
set "shortcut_path=%USERPROFILE%\Desktop\FB Speed Monitor.lnk"
set "target_path=%install_dir%\venv\Scripts\pythonw.exe"
set "arguments=%install_dir%\gui.py"
set "icon_path=%install_dir%\icon.ico"
set "working_dir=%install_dir%"

echo Erstelle Verknuepfung: %shortcut_path%
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%shortcut_path%'); $s.TargetPath = '%target_path%'; $s.Arguments = '%arguments%'; $s.IconLocation = '%icon_path%'; $s.WorkingDirectory = '%working_dir%'; $s.Save()"


:: --- 8. Abschluss und README anzeigen ---
echo.
echo ======================================================
echo Installation erfolgreich abgeschlossen!
echo ======================================================
echo.
echo Sie finden eine Verknuepfung auf Ihrem Desktop.
echo Eine Infodatei wird nun geoeffnet.
echo.
pause
start "" "%install_dir%\README.md"
goto :eof


:error
echo.
echo EIN FEHLER IST AUFGETRETEN. DIE INSTALLATION WURDE ABGEBROCHEN.
pause

:eof
endlocal