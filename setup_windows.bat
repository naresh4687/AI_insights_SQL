@echo off
rem InsightSQL setup for Windows: double-click this file.
rem Installs Python 3.12 if it is missing (with winget), then runs the guided setup
rem (setup_app.py), which installs everything else and can start the app.
setlocal
cd /d "%~dp0"

set "PY="
rem The Python launcher "py" first, then "python" (skipping the Microsoft Store placeholder).
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo Python 3.12 or newer was not found. Installing it with winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
    ) else (
        echo.
        echo Python could not be installed automatically.
        echo Install it from https://www.python.org/downloads/windows/
        echo and tick "Add python.exe to PATH" during the installation. Then double-click this file again.
        pause
        exit /b 1
    )
)

%PY% setup_app.py %*
echo.
pause
