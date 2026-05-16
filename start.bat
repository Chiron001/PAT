@echo off
setlocal enabledelayedexpansion
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   FIG Living — P.A.T Assessment System   ║
echo  ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: Try to find Python
set PYTHON=
for %%P in (python python3) do (
    %%P --version >nul 2>&1
    if !errorlevel! == 0 (
        set PYTHON=%%P
        goto :found_python
    )
)

:: Check common install paths
if exist "C:\Python312\python.exe"  set PYTHON=C:\Python312\python.exe  & goto :found_python
if exist "C:\Python311\python.exe"  set PYTHON=C:\Python311\python.exe  & goto :found_python
if exist "C:\Python310\python.exe"  set PYTHON=C:\Python310\python.exe  & goto :found_python
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe & goto :found_python
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe & goto :found_python

echo  [ERROR] Python not found on this system.
echo.
echo  Please install Python 3.10 or newer from:
echo     https://www.python.org/downloads/
echo.
echo  During installation, make sure to check:
echo     [x] Add Python to PATH
echo.
echo  Then run this file again.
echo.
pause
exit /b 1

:found_python
echo  [OK] Found Python: %PYTHON%

:: Setup venv on first run
if not exist "venv\Scripts\activate.bat" (
    echo  [SETUP] Creating virtual environment...
    %PYTHON% -m venv venv
    echo  [SETUP] Installing dependencies (flask, flask-cors, openpyxl)...
    venv\Scripts\pip install flask flask-cors openpyxl python-dotenv --quiet
    echo  [SETUP] Setup complete!
    echo.
)

echo  ┌─────────────────────────────────────────────┐
echo  │  Server Starting...                          │
echo  │                                              │
echo  │  Student Test  →  http://localhost:5000/     │
echo  │  Admin Panel   →  http://localhost:5000/admin│
echo  │  Admin Password:  FigLiving@2024             │
echo  │                                              │
echo  │  Press Ctrl+C to stop the server.            │
echo  └─────────────────────────────────────────────┘
echo.

venv\Scripts\python app.py

pause
