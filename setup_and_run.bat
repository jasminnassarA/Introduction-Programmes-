@echo off
rem ======================================================================
rem  One-click setup + launch for the dispatch dashboard.
rem   1. Finds Python 3.6-3.9 (installs Python 3.9.13 for this user if none)
rem   2. Creates .venv and installs requirements.txt (only when it changes)
rem   3. Checks for GAMS, opens the browser and starts the dashboard
rem ======================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PY_URL=https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe"
set "PY_LOCAL=%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
set "VENV_PY=.venv\Scripts\python.exe"
set "REQ_MARK=.venv\.req_installed"
set "URL=http://127.0.0.1:8050"
set "CHECK=import sys; sys.exit(0 if (3,6) <= sys.version_info[:2] <= (3,9) else 1)"

echo === Dispatch dashboard setup ===

rem ---------- 1. Find a suitable Python ----------
call :find_python
if not defined PY (
    echo No Python 3.6-3.9 found. Installing Python 3.9.13 for the current user...
    where winget >nul 2>&1
    if !errorlevel! equ 0 (
        winget install --id Python.Python.3.9 -e --scope user --silent --accept-package-agreements --accept-source-agreements
    )
    call :find_python
)
if not defined PY (
    echo Downloading the Python installer from python.org...
    curl -L -o "%TEMP%\python-3.9.13-amd64.exe" "%PY_URL%"
    if errorlevel 1 goto :fail_python
    "%TEMP%\python-3.9.13-amd64.exe" /quiet InstallAllUsers=0 Include_launcher=1 PrependPath=0 Include_test=0
    del "%TEMP%\python-3.9.13-amd64.exe" >nul 2>&1
    call :find_python
)
if not defined PY goto :fail_python
echo Using Python: !PY!

rem ---------- 2. Virtual environment ----------
rem A .venv without pyvenv.cfg is a broken leftover - rebuild it.
if exist .venv if not exist .venv\pyvenv.cfg (
    echo Removing incomplete .venv ...
    attrib -r .venv\* /s /d >nul 2>&1
    rmdir /s /q .venv
)
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "%CHECK%" >nul 2>&1
    if errorlevel 1 (
        echo Existing .venv uses an unsupported Python - rebuilding it...
        attrib -r .venv\* /s /d >nul 2>&1
    rmdir /s /q .venv
    )
)
if not exist "%VENV_PY%" (
    echo Creating virtual environment in .venv ...
    !PY! -m venv .venv
    if errorlevel 1 goto :fail
)

rem ---------- 3. Packages (only when requirements.txt changed) ----------
set "NEED_INSTALL=1"
if exist "%REQ_MARK%" (
    fc /b requirements.txt "%REQ_MARK%" >nul 2>&1 && set "NEED_INSTALL=0"
)
if "%NEED_INSTALL%"=="1" (
    echo Installing packages - this can take a few minutes the first time...
    "%VENV_PY%" -m pip install --upgrade "pip<22" >nul
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
    copy /y requirements.txt "%REQ_MARK%" >nul
) else (
    echo Packages already installed.
)

rem ---------- 4. GAMS check ----------
if not defined GAMS_DIR set "GAMS_DIR=C:\GAMS\win64\25.1"
if not exist "%GAMS_DIR%\gams.exe" (
    echo.
    echo WARNING: GAMS not found at "%GAMS_DIR%".
    echo   The dashboard needs GAMS to read the .gdx result files.
    echo   The dashboard will show the saved results, but changing capacities
    echo   ^(which re-solves the models^) and the Nodal page's "Re-run Nodal_SC" button
    echo   will not work until GAMS 25.1 is installed:
    echo   https://www.gams.com/download/   ^(or set GAMS_DIR to your install^)
    echo.
) else (
    rem GAMS Python API (gdxcc), needed by gdxpds to read .gdx files.
    "%VENV_PY%" -c "import gdxcc" >nul 2>&1
    if errorlevel 1 (
        for /f %%A in ('"%VENV_PY%" -c "import sys; print('api_%%d%%d' %% sys.version_info[:2])"') do set "API=%%A"
        if exist "%GAMS_DIR%\apifiles\Python\!API!\setup.py" (
            echo Installing the GAMS Python API ^(!API!^)...
            pushd "%GAMS_DIR%\apifiles\Python\!API!"
            "%~dp0%VENV_PY%" setup.py install >nul
            popd
        ) else (
            echo WARNING: GAMS at "%GAMS_DIR%" has no Python API for this Python ^(!API!^).
            echo   GAMS 25.1 only supports Python 3.6 - install Python 3.6 or a newer GAMS.
        )
    )
)

rem ---------- 5. Launch ----------
echo Starting dashboard at %URL%  ^(close this window to stop it^)
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 6; Start-Process '%URL%'"
set "DASH_DEBUG=0"
"%VENV_PY%" -m dashboard.app
pause
exit /b 0

rem ======================================================================
:find_python
set "PY="
rem 3.6 first: GAMS 25.1 only ships a Python API (gdxcc) for Python 3.6.
for %%V in (3.6 3.9 3.8 3.7) do (
    if not defined PY (
        py -%%V -c "%CHECK%" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY if exist "%PY_LOCAL%" (
    "%PY_LOCAL%" -c "%CHECK%" >nul 2>&1 && set "PY="%PY_LOCAL%""
)
exit /b 0

:fail_python
echo.
echo ERROR: Could not install Python 3.9 automatically.
echo Please install it manually from %PY_URL% and run this file again.
pause
exit /b 1

:fail
echo.
echo ERROR: Setup failed - see the messages above.
pause
exit /b 1
